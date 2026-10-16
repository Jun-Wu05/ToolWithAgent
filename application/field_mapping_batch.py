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


@dataclass(frozen=True)
class _BatchExecutionContext:
    """单次 run() 内各批处理阶段共享的调用上下文（闭包捕获变量的显式化，#358）。

    policy 刻意不入 ctx：它是 Runner 构造期定下的只读配置，继续走 self._policy。
    """

    plan_id: str
    step_id: str
    total_batches: int
    available_fields: list[str]
    semaphore: asyncio.Semaphore
    input_session: dict[str, Any]
    value_profiles: dict | None
    publish_progress: ProgressCallback


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
        policy = self._policy
        total_batches = (len(fields) + policy.batch_size - 1) // policy.batch_size
        ctx = _BatchExecutionContext(
            plan_id=plan_id,
            step_id=step_id,
            total_batches=total_batches,
            available_fields=list(fields),
            semaphore=asyncio.Semaphore(policy.max_concurrency),
            input_session={
                "simplified_data": {"original_log_sample": original_log_sample}
            },
            value_profiles=value_profiles,
            publish_progress=publish_progress,
        )

        tasks = [
            asyncio.create_task(self._execute_batch(ctx, index))
            for index in range(total_batches)
        ]
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

    async def _build_model_input(
        self,
        ctx: _BatchExecutionContext,
        fields_batch: list[str],
        batch_number: int,
        split_depth: int,
    ) -> str:
        """构造单批检索输入，并向进度汇发布 Embedding 检索的起止事件。"""
        retrieval_started_at = time.monotonic()
        await ctx.publish_progress(
            ProgressPhase.RETRIEVAL,
            ProgressStatus.RUNNING,
            "field_candidates_retrieving",
            current_batch=batch_number,
            total_batches=ctx.total_batches,
        )
        logger.info(
            "[MODEL_CALL_START] Embedding 调用开始: plan_id=%s step_id=%s "
            "batch=%s/%s split_depth=%s model=%s field_count=%s timeout_seconds=%s",
            ctx.plan_id,
            ctx.step_id,
            batch_number,
            ctx.total_batches,
            split_depth,
            "Qwen/Qwen3-Embedding-8B",
            len(fields_batch),
            30,
        )
        try:
            model_input = await asyncio.to_thread(
                build_batch_llm_input,
                "执行标准字段映射",
                ctx.input_session,
                fields_batch,
                batch_number,
                ctx.total_batches,
                prequery=self._candidate_retriever,
                value_profiles=ctx.value_profiles,
            )
        except Exception as error:
            elapsed = time.monotonic() - retrieval_started_at
            logger.warning(
                "[MODEL_CALL_FAILED] Embedding 调用失败: plan_id=%s step_id=%s "
                "batch=%s/%s split_depth=%s elapsed_seconds=%.3f error_category=%s",
                ctx.plan_id,
                ctx.step_id,
                batch_number,
                ctx.total_batches,
                split_depth,
                elapsed,
                type(error).__name__,
            )
            await ctx.publish_progress(
                ProgressPhase.RETRIEVAL,
                ProgressStatus.FAILED,
                "field_candidates_failed",
                current_batch=batch_number,
                total_batches=ctx.total_batches,
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
            ctx.plan_id,
            ctx.step_id,
            batch_number,
            ctx.total_batches,
            split_depth,
            elapsed,
            len(fields_batch),
        )
        await ctx.publish_progress(
            ProgressPhase.RETRIEVAL,
            ProgressStatus.SUCCESS,
            "field_candidates_ready",
            current_batch=batch_number,
            total_batches=ctx.total_batches,
            elapsed_seconds=elapsed,
        )
        return model_input

    async def _absorb_model_call_failure(
        self,
        ctx: _BatchExecutionContext,
        *,
        fields_batch: list[str],
        batch_number: int,
        split_depth: int,
        attempt: int,
        error: Exception,
    ) -> bool:
        """分类模型调用失败：超时抛 _ModelCallTimeout；可重试则等待并返回 True。

        不可重试或重试额度耗尽时返回 False，由调用方结束尝试循环。
        """
        origin = _timeout_origin(error)
        if origin is not None:
            logger.warning(
                "[MODEL_CALL_TIMEOUT] 专业模型调用超时: plan_id=%s step_id=%s "
                "operation=field_mapping batch=%s/%s split_depth=%s attempt=%s "
                "field_count=%s timeout_origin=%s watchdog_seconds=%s error_category=%s",
                ctx.plan_id,
                ctx.step_id,
                batch_number,
                ctx.total_batches,
                split_depth,
                attempt + 1,
                len(fields_batch),
                origin,
                self._policy.watchdog_timeout_seconds,
                type(error).__name__,
            )
            raise _ModelCallTimeout(origin, error) from error
        retriable = is_transient(error)
        logger.warning(
            "[MODEL_CALL_FAILED] 专业模型调用失败: plan_id=%s step_id=%s "
            "operation=field_mapping batch=%s/%s split_depth=%s attempt=%s "
            "error_category=%s retriable=%s",
            ctx.plan_id,
            ctx.step_id,
            batch_number,
            ctx.total_batches,
            split_depth,
            attempt + 1,
            type(error).__name__,
            retriable,
        )
        if not retriable or attempt >= self._policy.max_retries:
            return False
        retry_delay = _retry_delay_seconds(error, self._policy.retry_delay_seconds)
        logger.info(
            "[BATCH_RETRY] 字段映射批次重试: plan_id=%s step_id=%s "
            "batch=%s/%s split_depth=%s next_attempt=%s delay_seconds=%s",
            ctx.plan_id,
            ctx.step_id,
            batch_number,
            ctx.total_batches,
            split_depth,
            attempt + 2,
            retry_delay,
        )
        await ctx.publish_progress(
            ProgressPhase.MODEL_CALL,
            ProgressStatus.RUNNING,
            "field_mapping_batch_retry",
            current_batch=batch_number,
            total_batches=ctx.total_batches,
        )
        await asyncio.sleep(retry_delay)
        return True

    async def _call_model(
        self,
        ctx: _BatchExecutionContext,
        fields_batch: list[str],
        batch_number: int,
        split_depth: int,
    ) -> list[dict[str, Any]]:
        """带重试与 watchdog 的单批模型调用；成功后立即归一化并补查缺失字段。"""
        policy = self._policy
        model_input = await self._build_model_input(
            ctx, fields_batch, batch_number, split_depth
        )
        last_error: Exception = RuntimeError("模型调用未开始")
        for attempt in range(policy.max_retries + 1):
            model_started_at = time.monotonic()
            await ctx.publish_progress(
                ProgressPhase.MODEL_CALL,
                ProgressStatus.RUNNING,
                "field_mapping_batch_running",
                current_batch=batch_number,
                total_batches=ctx.total_batches,
            )
            logger.info(
                "[MODEL_CALL_START] 专业模型调用开始: plan_id=%s step_id=%s "
                "operation=field_mapping batch=%s/%s split_depth=%s attempt=%s "
                "field_count=%s model_input_length=%s watchdog_seconds=%s",
                ctx.plan_id,
                ctx.step_id,
                batch_number,
                ctx.total_batches,
                split_depth,
                attempt + 1,
                len(fields_batch),
                len(model_input),
                policy.watchdog_timeout_seconds,
            )
            try:
                async with ctx.semaphore:
                    content = await asyncio.wait_for(
                        self._run_member(
                            model_input,
                            plan_id=ctx.plan_id,
                            step_id=ctx.step_id,
                            batch_number=batch_number,
                        ),
                        timeout=policy.watchdog_timeout_seconds,
                    )
            except Exception as error:
                last_error = error
                if await self._absorb_model_call_failure(
                    ctx,
                    fields_batch=fields_batch,
                    batch_number=batch_number,
                    split_depth=split_depth,
                    attempt=attempt,
                    error=error,
                ):
                    continue
                break

            elapsed = time.monotonic() - model_started_at
            logger.info(
                "[MODEL_CALL_END] 专业模型调用完成: plan_id=%s step_id=%s "
                "operation=field_mapping batch=%s/%s split_depth=%s attempt=%s "
                "field_count=%s elapsed_seconds=%.3f",
                ctx.plan_id,
                ctx.step_id,
                batch_number,
                ctx.total_batches,
                split_depth,
                attempt + 1,
                len(fields_batch),
                elapsed,
            )
            await ctx.publish_progress(
                ProgressPhase.MODEL_CALL,
                ProgressStatus.SUCCESS,
                "field_mapping_batch_completed",
                current_batch=batch_number,
                total_batches=ctx.total_batches,
                elapsed_seconds=elapsed,
            )
            return await self._backfill_rows(
                parse_json_mapping_result(content),
                fields_batch,
                input_session=ctx.input_session,
                plan_id=ctx.plan_id,
                step_id=ctx.step_id,
                batch_number=batch_number,
                total_batches=ctx.total_batches,
                semaphore=ctx.semaphore,
                value_profiles=ctx.value_profiles,
            )

        raise FieldMappingBatchError(
            batch_number,
            "field_mapping_model_failed",
            f"第 {batch_number} 批字段映射失败: {type(last_error).__name__}",
        )

    async def _execute_fields(
        self,
        ctx: _BatchExecutionContext,
        fields_batch: list[str],
        batch_number: int,
        split_depth: int,
    ) -> list[dict[str, Any]]:
        """单批字段执行；watchdog 超时按策略自递归拆分为子批。"""
        batch_started_at = time.monotonic()
        try:
            rows = await self._call_model(ctx, fields_batch, batch_number, split_depth)
        except _ModelCallTimeout as timeout:
            can_split = (
                split_depth < self._policy.max_timeout_split_depth
                and len(fields_batch) > 1
            )
            if not can_split:
                raise FieldMappingBatchError(
                    batch_number,
                    "field_mapping_timeout",
                    f"第 {batch_number} 批字段映射失败: {type(timeout.error).__name__}",
                ) from timeout
            child_batches = [
                fields_batch[index : index + self._policy.timeout_split_size]
                for index in range(0, len(fields_batch), self._policy.timeout_split_size)
            ]
            logger.warning(
                "[BATCH_TIMEOUT_SPLIT] 超时批拆分: plan_id=%s step_id=%s "
                "batch=%s/%s timeout_origin=%s split_depth=%s child_sizes=%s",
                ctx.plan_id,
                ctx.step_id,
                batch_number,
                ctx.total_batches,
                timeout.origin,
                split_depth + 1,
                [len(child) for child in child_batches],
            )
            child_results = await asyncio.gather(
                *(
                    self._execute_fields(ctx, child, batch_number, split_depth + 1)
                    for child in child_batches
                )
            )
            rows = [row for child_rows in child_results for row in child_rows]

        logger.info(
            "[BATCH_END] 字段映射批次完成: plan_id=%s step_id=%s "
            "batch=%s/%s split_depth=%s field_count=%s elapsed_seconds=%.3f",
            ctx.plan_id,
            ctx.step_id,
            batch_number,
            ctx.total_batches,
            split_depth,
            len(rows),
            time.monotonic() - batch_started_at,
        )
        return rows

    async def _execute_batch(
        self,
        ctx: _BatchExecutionContext,
        batch_index: int,
    ) -> tuple[int, list[dict[str, Any]]]:
        """切片第 batch_index 批并执行，返回 (批次序号, 该批行)。"""
        fields_batch = ctx.available_fields[
            batch_index * self._policy.batch_size : (batch_index + 1) * self._policy.batch_size
        ]
        batch_number = batch_index + 1
        logger.info(
            "[BATCH_START] 字段映射批次开始: plan_id=%s step_id=%s "
            "batch=%s/%s field_count=%s",
            ctx.plan_id,
            ctx.step_id,
            batch_number,
            ctx.total_batches,
            len(fields_batch),
        )
        return batch_index, await self._execute_fields(
            ctx, fields_batch, batch_number, 0
        )


__all__ = [
    "FieldMappingBatchError",
    "FieldMappingBatchRunner",
    "FieldMappingExecutionPolicy",
]
