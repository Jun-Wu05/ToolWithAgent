"""字段映射批处理运行器：冻结模型调用策略，不接触会话与业务写回。"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from agent.shared.logger import get_logger

from application.adapters.shared import (
    _retry_delay_seconds,
    run_member_stream,
)
from application.field_mapping_input import build_batch_llm_input
from application.parsing import parse_json_mapping_result
from application.recovery import is_transient
from contracts.progress import ProgressPhase, ProgressStatus


logger = get_logger("execution_adapters")

ProgressCallback = Callable[..., Awaitable[None]]


@dataclass(frozen=True)
class FieldMappingExecutionPolicy:
    """定义字段映射批处理的并发、超时和重试边界。"""

    batch_size: int = 25
    max_concurrency: int = 3
    watchdog_timeout_seconds: float = 105.0
    max_retries: int = 1
    retry_delay_seconds: float = 2.0
    backfill_max_attempts: int = 2
    timeout_split_size: int = 13
    max_timeout_split_depth: int = 1


class FieldMappingBatchError(RuntimeError):
    """描述可定位到具体批次的字段映射失败。"""

    def __init__(self, batch_number: int, error_code: str, message: str) -> None:
        """保存批次、稳定错误码和安全错误消息。"""
        super().__init__(message)
        self.batch_number = batch_number
        self.error_code = error_code


class _ModelCallTimeout(RuntimeError):
    """携带稳定超时来源，避免 Provider 与 Runner deadline 混淆。"""

    def __init__(self, origin: str, error: Exception) -> None:
        super().__init__(str(error))
        self.origin = origin
        self.error = error


def _timeout_origin(error: Exception) -> str | None:
    """按异常类型区分 SDK 主动超时与 Runner watchdog 超时。"""
    if type(error).__name__ in {
        "APITimeoutError",
        "ConnectTimeout",
        "ReadTimeout",
        "WriteTimeout",
    }:
        return "provider_sdk"
    if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
        return "adapter_watchdog"
    return None


class FieldMappingBatchRunner:
    """执行字段映射批次并返回与输入字段等长、同序的原始映射行。"""

    def __init__(
        self,
        team: Any,
        policy: FieldMappingExecutionPolicy | None = None,
        candidate_retriever: Any | None = None,
    ) -> None:
        self._team = team
        self._policy = policy or FieldMappingExecutionPolicy()
        self._candidate_retriever = candidate_retriever

    async def _run_member(
        self,
        model_input: str,
        *,
        plan_id: str,
        step_id: str,
        batch_number: int,
    ) -> Any:
        return await run_member_stream(
            self._team,
            "FieldMappingAgent",
            model_input,
            plan_id=plan_id,
            step_id=step_id,
            batch_number=batch_number,
        )

    async def _backfill_rows(
        self,
        batch_rows: list[dict[str, Any]],
        fields_batch: list[str],
        *,
        input_session: dict[str, Any],
        plan_id: str,
        step_id: str,
        batch_number: int,
        total_batches: int,
        semaphore: asyncio.Semaphore,
        value_profiles: dict | None = None,
    ) -> list[dict[str, Any]]:
        """去重、过滤批次外结果、补查缺失字段，并严格恢复输入顺序。"""
        fields_set = set(fields_batch)
        covered: dict[str, dict[str, Any]] = {}
        duplicate_count = 0
        extra_count = 0
        for row in batch_rows:
            name = str(row.get("原始字段名", "")).strip()
            if not name:
                continue
            if name not in fields_set:
                extra_count += 1
                continue
            if name in covered:
                duplicate_count += 1
                continue
            covered[name] = row

        missing = [field for field in fields_batch if field not in covered]
        for attempt in range(self._policy.backfill_max_attempts):
            if not missing:
                break
            logger.info(
                "[BATCH_BACKFILL] 补查缺失字段: plan_id=%s step_id=%s batch=%s/%s "
                "attempt=%s missing_count=%s",
                plan_id,
                step_id,
                batch_number,
                total_batches,
                attempt + 1,
                len(missing),
            )
            try:
                backfill_input = await asyncio.to_thread(
                    build_batch_llm_input,
                    "补查标准字段映射",
                    input_session,
                    missing,
                    batch_number,
                    total_batches,
                    prequery=self._candidate_retriever,
                    value_profiles=value_profiles,
                )
                async with semaphore:
                    content = await asyncio.wait_for(
                        self._run_member(
                            backfill_input,
                            plan_id=plan_id,
                            step_id=step_id,
                            batch_number=batch_number,
                        ),
                        timeout=self._policy.watchdog_timeout_seconds,
                    )
            except Exception as error:  # noqa: BLE001 - 补查失败按冻结策略兜底
                logger.warning(
                    "[BATCH_BACKFILL] 补查调用失败，停止补查并兜底未匹配: "
                    "plan_id=%s step_id=%s batch=%s/%s error_category=%s remaining_count=%s",
                    plan_id,
                    step_id,
                    batch_number,
                    total_batches,
                    type(error).__name__,
                    len(missing),
                )
                break
            for row in parse_json_mapping_result(content):
                name = str(row.get("原始字段名", "")).strip()
                if not name or name not in fields_set or name in covered:
                    continue
                covered[name] = row
            missing = [field for field in fields_batch if field not in covered]

        fallback_count = 0
        for field in missing:
            covered[field] = {
                "原始字段名": field,
                "系统属性名称": "未匹配",
                "匹配状态": "未匹配",
            }
            fallback_count += 1

        if duplicate_count or extra_count or fallback_count:
            logger.warning(
                "[BATCH_NORMALIZED] 批次结果归一化: plan_id=%s step_id=%s batch=%s/%s "
                "duplicate_count=%s extra_count=%s fallback_count=%s",
                plan_id,
                step_id,
                batch_number,
                total_batches,
                duplicate_count,
                extra_count,
                fallback_count,
            )
        return [{**covered[field], "原始字段名": field} for field in fields_batch]

    async def run(
        self,
        fields: list[str],
        *,
        original_log_sample: Any,
        plan_id: str,
        step_id: str,
        publish_progress: ProgressCallback,
        value_profiles: dict | None = None,
    ) -> list[dict[str, Any]]:
        """执行完整批次策略；任一原始批失败时取消其余任务并原子失败。"""
        available_fields = list(fields)
        policy = self._policy
        total_batches = (len(available_fields) + policy.batch_size - 1) // policy.batch_size
        semaphore = asyncio.Semaphore(policy.max_concurrency)
        input_session = {
            "simplified_data": {"original_log_sample": original_log_sample}
        }

        async def build_model_input(
            fields_batch: list[str], batch_number: int, split_depth: int
        ) -> str:
            retrieval_started_at = time.monotonic()
            await publish_progress(
                ProgressPhase.RETRIEVAL,
                ProgressStatus.RUNNING,
                "field_candidates_retrieving",
                current_batch=batch_number,
                total_batches=total_batches,
            )
            logger.info(
                "[MODEL_CALL_START] Embedding 调用开始: plan_id=%s step_id=%s "
                "batch=%s/%s split_depth=%s model=%s field_count=%s timeout_seconds=%s",
                plan_id,
                step_id,
                batch_number,
                total_batches,
                split_depth,
                "Qwen/Qwen3-Embedding-8B",
                len(fields_batch),
                30,
            )
            try:
                model_input = await asyncio.to_thread(
                    build_batch_llm_input,
                    "执行标准字段映射",
                    input_session,
                    fields_batch,
                    batch_number,
                    total_batches,
                    prequery=self._candidate_retriever,
                    value_profiles=value_profiles,
                )
            except Exception as error:
                elapsed = time.monotonic() - retrieval_started_at
                logger.warning(
                    "[MODEL_CALL_FAILED] Embedding 调用失败: plan_id=%s step_id=%s "
                    "batch=%s/%s split_depth=%s elapsed_seconds=%.3f error_category=%s",
                    plan_id,
                    step_id,
                    batch_number,
                    total_batches,
                    split_depth,
                    elapsed,
                    type(error).__name__,
                )
                await publish_progress(
                    ProgressPhase.RETRIEVAL,
                    ProgressStatus.FAILED,
                    "field_candidates_failed",
                    current_batch=batch_number,
                    total_batches=total_batches,
                    elapsed_seconds=elapsed,
                )
                raise FieldMappingBatchError(
                    batch_number,
                    "field_retrieval_failed",
                    f"第 {batch_number} 批字段候选检索失败",
                ) from error
            elapsed = time.monotonic() - retrieval_started_at
            logger.info(
                "[MODEL_CALL_END] Embedding 调用完成: plan_id=%s step_id=%s "
                "batch=%s/%s split_depth=%s elapsed_seconds=%.3f field_count=%s",
                plan_id,
                step_id,
                batch_number,
                total_batches,
                split_depth,
                elapsed,
                len(fields_batch),
            )
            await publish_progress(
                ProgressPhase.RETRIEVAL,
                ProgressStatus.SUCCESS,
                "field_candidates_ready",
                current_batch=batch_number,
                total_batches=total_batches,
                elapsed_seconds=elapsed,
            )
            return model_input

        async def call_model(
            fields_batch: list[str], batch_number: int, split_depth: int
        ) -> list[dict[str, Any]]:
            model_input = await build_model_input(fields_batch, batch_number, split_depth)
            last_error: Exception = RuntimeError("模型调用未开始")
            for attempt in range(policy.max_retries + 1):
                model_started_at = time.monotonic()
                await publish_progress(
                    ProgressPhase.MODEL_CALL,
                    ProgressStatus.RUNNING,
                    "field_mapping_batch_running",
                    current_batch=batch_number,
                    total_batches=total_batches,
                )
                logger.info(
                    "[MODEL_CALL_START] 专业模型调用开始: plan_id=%s step_id=%s "
                    "operation=field_mapping batch=%s/%s split_depth=%s attempt=%s "
                    "field_count=%s model_input_length=%s watchdog_seconds=%s",
                    plan_id,
                    step_id,
                    batch_number,
                    total_batches,
                    split_depth,
                    attempt + 1,
                    len(fields_batch),
                    len(model_input),
                    policy.watchdog_timeout_seconds,
                )
                try:
                    async with semaphore:
                        content = await asyncio.wait_for(
                            self._run_member(
                                model_input,
                                plan_id=plan_id,
                                step_id=step_id,
                                batch_number=batch_number,
                            ),
                            timeout=policy.watchdog_timeout_seconds,
                        )
                except Exception as error:
                    last_error = error
                    origin = _timeout_origin(error)
                    if origin is not None:
                        logger.warning(
                            "[MODEL_CALL_TIMEOUT] 专业模型调用超时: plan_id=%s step_id=%s "
                            "operation=field_mapping batch=%s/%s split_depth=%s attempt=%s "
                            "field_count=%s timeout_origin=%s watchdog_seconds=%s error_category=%s",
                            plan_id,
                            step_id,
                            batch_number,
                            total_batches,
                            split_depth,
                            attempt + 1,
                            len(fields_batch),
                            origin,
                            policy.watchdog_timeout_seconds,
                            type(error).__name__,
                        )
                        raise _ModelCallTimeout(origin, error) from error
                    retriable = is_transient(error)
                    logger.warning(
                        "[MODEL_CALL_FAILED] 专业模型调用失败: plan_id=%s step_id=%s "
                        "operation=field_mapping batch=%s/%s split_depth=%s attempt=%s "
                        "error_category=%s retriable=%s",
                        plan_id,
                        step_id,
                        batch_number,
                        total_batches,
                        split_depth,
                        attempt + 1,
                        type(error).__name__,
                        retriable,
                    )
                    if not retriable or attempt >= policy.max_retries:
                        break
                    retry_delay = _retry_delay_seconds(error, policy.retry_delay_seconds)
                    logger.info(
                        "[BATCH_RETRY] 字段映射批次重试: plan_id=%s step_id=%s "
                        "batch=%s/%s split_depth=%s next_attempt=%s delay_seconds=%s",
                        plan_id,
                        step_id,
                        batch_number,
                        total_batches,
                        split_depth,
                        attempt + 2,
                        retry_delay,
                    )
                    await publish_progress(
                        ProgressPhase.MODEL_CALL,
                        ProgressStatus.RUNNING,
                        "field_mapping_batch_retry",
                        current_batch=batch_number,
                        total_batches=total_batches,
                    )
                    await asyncio.sleep(retry_delay)
                    continue

                elapsed = time.monotonic() - model_started_at
                logger.info(
                    "[MODEL_CALL_END] 专业模型调用完成: plan_id=%s step_id=%s "
                    "operation=field_mapping batch=%s/%s split_depth=%s attempt=%s "
                    "field_count=%s elapsed_seconds=%.3f",
                    plan_id,
                    step_id,
                    batch_number,
                    total_batches,
                    split_depth,
                    attempt + 1,
                    len(fields_batch),
                    elapsed,
                )
                await publish_progress(
                    ProgressPhase.MODEL_CALL,
                    ProgressStatus.SUCCESS,
                    "field_mapping_batch_completed",
                    current_batch=batch_number,
                    total_batches=total_batches,
                    elapsed_seconds=elapsed,
                )
                return await self._backfill_rows(
                    parse_json_mapping_result(content),
                    fields_batch,
                    input_session=input_session,
                    plan_id=plan_id,
                    step_id=step_id,
                    batch_number=batch_number,
                    total_batches=total_batches,
                    semaphore=semaphore,
                    value_profiles=value_profiles,
                )

            raise FieldMappingBatchError(
                batch_number,
                "field_mapping_model_failed",
                f"第 {batch_number} 批字段映射失败: {type(last_error).__name__}",
            )

        async def execute_fields(
            fields_batch: list[str], batch_number: int, split_depth: int
        ) -> list[dict[str, Any]]:
            batch_started_at = time.monotonic()
            try:
                rows = await call_model(fields_batch, batch_number, split_depth)
            except _ModelCallTimeout as timeout:
                can_split = (
                    split_depth < policy.max_timeout_split_depth
                    and len(fields_batch) > 1
                )
                if not can_split:
                    raise FieldMappingBatchError(
                        batch_number,
                        "field_mapping_timeout",
                        f"第 {batch_number} 批字段映射失败: {type(timeout.error).__name__}",
                    ) from timeout
                child_batches = [
                    fields_batch[index : index + policy.timeout_split_size]
                    for index in range(0, len(fields_batch), policy.timeout_split_size)
                ]
                logger.warning(
                    "[BATCH_TIMEOUT_SPLIT] 超时批拆分: plan_id=%s step_id=%s "
                    "batch=%s/%s timeout_origin=%s split_depth=%s child_sizes=%s",
                    plan_id,
                    step_id,
                    batch_number,
                    total_batches,
                    timeout.origin,
                    split_depth + 1,
                    [len(child) for child in child_batches],
                )
                child_results = await asyncio.gather(
                    *(execute_fields(child, batch_number, split_depth + 1) for child in child_batches)
                )
                rows = [row for child_rows in child_results for row in child_rows]

            logger.info(
                "[BATCH_END] 字段映射批次完成: plan_id=%s step_id=%s "
                "batch=%s/%s split_depth=%s field_count=%s elapsed_seconds=%.3f",
                plan_id,
                step_id,
                batch_number,
                total_batches,
                split_depth,
                len(rows),
                time.monotonic() - batch_started_at,
            )
            return rows

        async def execute_batch(batch_index: int) -> tuple[int, list[dict[str, Any]]]:
            fields_batch = available_fields[
                batch_index * policy.batch_size : (batch_index + 1) * policy.batch_size
            ]
            batch_number = batch_index + 1
            logger.info(
                "[BATCH_START] 字段映射批次开始: plan_id=%s step_id=%s "
                "batch=%s/%s field_count=%s",
                plan_id,
                step_id,
                batch_number,
                total_batches,
                len(fields_batch),
            )
            return batch_index, await execute_fields(fields_batch, batch_number, 0)

        tasks = [asyncio.create_task(execute_batch(index)) for index in range(total_batches)]
        try:
            completed_batches = await asyncio.gather(*tasks)
        except FieldMappingBatchError:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

        return [
            row
            for _, batch_rows in sorted(completed_batches, key=lambda item: item[0])
            for row in batch_rows
        ]


__all__ = [
    "FieldMappingBatchError",
    "FieldMappingBatchRunner",
    "FieldMappingExecutionPolicy",
]
