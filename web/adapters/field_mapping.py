"""字段映射适配器：并发批处理、超时拆批、补查与原子写回（Issue #88 拆分自 execution_adapters）。"""

from __future__ import annotations

import asyncio
import copy
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from agent.shared.logger import get_logger

from application.execution import ExecutionContext
from contracts.progress import ProgressPhase, ProgressStatus
from contracts.planner_models import (
    FieldMappingArtifact,
    FieldMappingRow,
    FieldMappingStep,
    StepResult,
)
from application.adapters.shared import (
    REPO_ROOT,
    _build_config_artifact,
    _count_tagged_normalize,
    _failed,
    _is_retriable_model_error,
    _publish_progress,
    _retry_delay_seconds,
    _session_get,
    _session_set,
    _success,
    run_member_stream,
)


logger = get_logger("execution_adapters")

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


class FieldMappingAdapter:
    """并发执行字段映射；超时批只拆分一层，全部成功后才原子写回。"""

    def __init__(
        self,
        team: Any,
        mapping_policy: FieldMappingExecutionPolicy | None = None,
        candidate_retriever: Any | None = None,
        object_map_loader: Any | None = None,
        event_classifier: Any | None = None,
    ) -> None:
        """保存专业 Agent 注册表、执行策略与可注入依赖。

        candidate_retriever / object_map_loader 缺省时回落模块默认实现
        （Issue #88 依赖注入接缝，与 PlannerService(runner=...) 同构）；
        测试传构造假件，不 monkeypatch 模块私有属性。
        event_classifier 是事件名称判定的 LLM 假件接缝（PRD #124）。
        """
        self._team = team
        self._mapping_policy = mapping_policy or FieldMappingExecutionPolicy()
        self._candidate_retriever = candidate_retriever
        self._object_map_loader = object_map_loader
        self._event_classifier = event_classifier

    async def execute(
        self,
        step: FieldMappingStep,
        context: ExecutionContext,
        dependencies: Mapping[str, StepResult] | None = None,
    ) -> StepResult:
        """执行字段映射步骤；行为与原 ProfessionalAgentAdapter 完全一致。"""
        if not isinstance(step, FieldMappingStep):
            raise TypeError("FieldMappingAdapter 只接受 FieldMappingStep")
        return await self._execute_field_mapping(step, context)

    async def _run_member(
        self,
        member_name: str,
        model_input: str,
        *,
        plan_id: str = "pending",
        step_id: str = "pending",
        batch_number: int | None = None,
    ) -> Any:
        """委托共享事件流消费，保持原 ProfessionalAgentAdapter 调用面。"""
        return await run_member_stream(
            self._team,
            member_name,
            model_input,
            plan_id=plan_id,
            step_id=step_id,
            batch_number=batch_number,
        )

    async def _backfill_field_mapping_rows(
        self,
        batch_rows: list[dict[str, Any]],
        fields_batch: list[str],
        context: ExecutionContext,
        step: FieldMappingStep,
        batch_number: int,
        total_batches: int,
        semaphore: asyncio.Semaphore,
    ) -> list[dict[str, Any]]:
        """补齐模型漏掉的字段，仍缺失则兜底为「未匹配」，避免单字段缺失作废整步。

        模型在 25 字段大 batch 上常漏 1～2 个字段（如线上 24/25）。这里先按字段名
        去重归集、忽略批次外字段，再对缺失字段单独补查（重试 backfill_max_attempts
        次），最后仍缺的标记「未匹配」。返回值严格按 fields_batch 顺序、数量一致，
        原始字段名归一为输入名，顺带消除了旧校验对返回顺序的敏感。
        """
        from web.input_builder import build_batch_llm_input
        from web.parsers import parse_json_mapping_result

        policy = self._mapping_policy
        fields_set = set(fields_batch)

        # 按字段名归集模型返回；键以 strip 后比对以容忍首尾空白漂移。
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
        for attempt in range(policy.backfill_max_attempts):
            if not missing:
                break
            logger.info(
                "[BATCH_BACKFILL] 补查缺失字段: plan_id=%s step_id=%s batch=%s/%s "
                "attempt=%s missing_count=%s",
                context.plan_id,
                step.step_id,
                batch_number,
                total_batches,
                attempt + 1,
                len(missing),
            )
            try:
                backfill_input = await asyncio.to_thread(
                    build_batch_llm_input,
                    "补查标准字段映射",
                    context.session,
                    missing,
                    batch_number,
                    total_batches,
                    prequery=self._candidate_retriever,
                )
                async with semaphore:
                    content = await asyncio.wait_for(
                        self._run_member(
                            "FieldMappingAgent",
                            backfill_input,
                            plan_id=context.plan_id,
                            step_id=step.step_id,
                            batch_number=batch_number,
                        ),
                        timeout=policy.watchdog_timeout_seconds,
                    )
            except Exception as error:
                logger.warning(
                    "[BATCH_BACKFILL] 补查调用失败，停止补查并兜底未匹配: "
                    "plan_id=%s step_id=%s batch=%s/%s error_category=%s remaining_count=%s",
                    context.plan_id,
                    step.step_id,
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

        # 仍缺失的字段兜底为「未匹配」，保证每个输入字段都有结果，避免整步作废。
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
                context.plan_id,
                step.step_id,
                batch_number,
                total_batches,
                duplicate_count,
                extra_count,
                fallback_count,
            )

        # 按 fields_batch 顺序输出，原始字段名归一为输入名，保证下游顺序与数量一致。
        return [{**covered[field], "原始字段名": field} for field in fields_batch]

    async def _execute_field_mapping(
        self,
        step: FieldMappingStep,
        context: ExecutionContext,
    ) -> StepResult:
        """并发执行字段映射；超时批只拆分一层，全部成功后才原子写回。"""
        from web.input_builder import build_batch_llm_input
        from web.parsers import parse_json_mapping_result

        available_fields = list(context.session_facts.available_fields)
        policy = self._mapping_policy
        total_batches = (len(available_fields) + policy.batch_size - 1) // policy.batch_size
        semaphore = asyncio.Semaphore(policy.max_concurrency)

        class ModelCallTimeout(RuntimeError):
            """携带稳定超时来源，避免 Provider 与 Adapter deadline 混淆。"""

            def __init__(self, origin: str, error: Exception) -> None:
                """保存稳定来源和底层异常，供拆批决策及安全错误消息使用。"""
                super().__init__(str(error))
                self.origin = origin
                self.error = error

        def timeout_origin(error: Exception) -> str | None:
            """按异常类型区分 SDK 主动超时与 Adapter watchdog 超时。"""
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

        async def build_model_input(
            fields_batch: list[str],
            batch_number: int,
            split_depth: int,
        ) -> str:
            """为原始批或子批检索候选；检索失败仍按原始批原子失败。"""
            retrieval_started_at = time.monotonic()
            await _publish_progress(
                context,
                step,
                ProgressPhase.RETRIEVAL,
                ProgressStatus.RUNNING,
                "field_candidates_retrieving",
                current_batch=batch_number,
                total_batches=total_batches,
            )
            logger.info(
                "[MODEL_CALL_START] Embedding 调用开始: plan_id=%s step_id=%s "
                "batch=%s/%s split_depth=%s model=%s field_count=%s timeout_seconds=%s",
                context.plan_id,
                step.step_id,
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
                    context.session,
                    fields_batch,
                    batch_number,
                    total_batches,
                    prequery=self._candidate_retriever,
                )
            except Exception as error:
                retrieval_elapsed = time.monotonic() - retrieval_started_at
                logger.warning(
                    "[MODEL_CALL_FAILED] Embedding 调用失败: plan_id=%s step_id=%s "
                    "batch=%s/%s split_depth=%s elapsed_seconds=%.3f error_category=%s",
                    context.plan_id,
                    step.step_id,
                    batch_number,
                    total_batches,
                    split_depth,
                    retrieval_elapsed,
                    type(error).__name__,
                )
                await _publish_progress(
                    context,
                    step,
                    ProgressPhase.RETRIEVAL,
                    ProgressStatus.FAILED,
                    "field_candidates_failed",
                    current_batch=batch_number,
                    total_batches=total_batches,
                    elapsed_seconds=retrieval_elapsed,
                )
                raise FieldMappingBatchError(
                    batch_number,
                    "field_retrieval_failed",
                    f"第 {batch_number} 批字段候选检索失败",
                ) from error
            retrieval_elapsed = time.monotonic() - retrieval_started_at
            logger.info(
                "[MODEL_CALL_END] Embedding 调用完成: plan_id=%s step_id=%s "
                "batch=%s/%s split_depth=%s elapsed_seconds=%.3f field_count=%s",
                context.plan_id,
                step.step_id,
                batch_number,
                total_batches,
                split_depth,
                retrieval_elapsed,
                len(fields_batch),
            )
            await _publish_progress(
                context,
                step,
                ProgressPhase.RETRIEVAL,
                ProgressStatus.SUCCESS,
                "field_candidates_ready",
                current_batch=batch_number,
                total_batches=total_batches,
                elapsed_seconds=retrieval_elapsed,
            )
            return model_input

        async def call_model(
            fields_batch: list[str],
            batch_number: int,
            split_depth: int,
        ) -> list[dict[str, Any]]:
            """每次模型尝试独立占用并发槽；等待重试或拆批时不持有槽。"""
            model_input = await build_model_input(fields_batch, batch_number, split_depth)
            last_error: Exception = RuntimeError("模型调用未开始")
            error_code = "field_mapping_model_failed"
            for attempt in range(policy.max_retries + 1):
                model_started_at = time.monotonic()
                await _publish_progress(
                    context,
                    step,
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
                    context.plan_id,
                    step.step_id,
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
                                "FieldMappingAgent",
                                model_input,
                                plan_id=context.plan_id,
                                step_id=step.step_id,
                                batch_number=batch_number,
                            ),
                            timeout=policy.watchdog_timeout_seconds,
                        )
                except Exception as error:
                    last_error = error
                    origin = timeout_origin(error)
                    if origin is not None:
                        logger.warning(
                            "[MODEL_CALL_TIMEOUT] 专业模型调用超时: plan_id=%s step_id=%s "
                            "operation=field_mapping batch=%s/%s split_depth=%s attempt=%s "
                            "field_count=%s timeout_origin=%s watchdog_seconds=%s "
                            "error_category=%s",
                            context.plan_id,
                            step.step_id,
                            batch_number,
                            total_batches,
                            split_depth,
                            attempt + 1,
                            len(fields_batch),
                            origin,
                            policy.watchdog_timeout_seconds,
                            type(error).__name__,
                        )
                        raise ModelCallTimeout(origin, error) from error

                    retriable = _is_retriable_model_error(error)
                    logger.warning(
                        "[MODEL_CALL_FAILED] 专业模型调用失败: plan_id=%s step_id=%s "
                        "operation=field_mapping batch=%s/%s split_depth=%s attempt=%s "
                        "error_category=%s retriable=%s",
                        context.plan_id,
                        step.step_id,
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
                        context.plan_id,
                        step.step_id,
                        batch_number,
                        total_batches,
                        split_depth,
                        attempt + 2,
                        retry_delay,
                    )
                    await _publish_progress(
                        context,
                        step,
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
                    context.plan_id,
                    step.step_id,
                    batch_number,
                    total_batches,
                    split_depth,
                    attempt + 1,
                    len(fields_batch),
                    elapsed,
                )
                await _publish_progress(
                    context,
                    step,
                    ProgressPhase.MODEL_CALL,
                    ProgressStatus.SUCCESS,
                    "field_mapping_batch_completed",
                    current_batch=batch_number,
                    total_batches=total_batches,
                    elapsed_seconds=elapsed,
                )
                batch_rows = parse_json_mapping_result(content)
                return await self._backfill_field_mapping_rows(
                    batch_rows,
                    fields_batch,
                    context,
                    step,
                    batch_number,
                    total_batches,
                    semaphore,
                )

            raise FieldMappingBatchError(
                batch_number,
                error_code,
                f"第 {batch_number} 批字段映射失败: {type(last_error).__name__}",
            )

        async def execute_fields(
            fields_batch: list[str],
            batch_number: int,
            split_depth: int,
        ) -> list[dict[str, Any]]:
            """执行字段集合；仅超时可触发一次受限拆批。"""
            batch_started_at = time.monotonic()
            try:
                rows = await call_model(fields_batch, batch_number, split_depth)
            except ModelCallTimeout as timeout:
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
                    context.plan_id,
                    step.step_id,
                    batch_number,
                    total_batches,
                    timeout.origin,
                    split_depth + 1,
                    [len(child) for child in child_batches],
                )
                child_results = await asyncio.gather(
                    *(
                        execute_fields(child, batch_number, split_depth + 1)
                        for child in child_batches
                    )
                )
                rows = [row for child_rows in child_results for row in child_rows]

            logger.info(
                "[BATCH_END] 字段映射批次完成: plan_id=%s step_id=%s "
                "batch=%s/%s split_depth=%s field_count=%s elapsed_seconds=%.3f",
                context.plan_id,
                step.step_id,
                batch_number,
                total_batches,
                split_depth,
                len(rows),
                time.monotonic() - batch_started_at,
            )
            return rows

        async def execute_batch(batch_index: int) -> tuple[int, list[dict[str, Any]]]:
            """按正常 25 字段策略启动原始批，拆分仅由该批超时触发。"""
            fields_batch = available_fields[
                batch_index * policy.batch_size : (batch_index + 1) * policy.batch_size
            ]
            batch_number = batch_index + 1
            logger.info(
                "[BATCH_START] 字段映射批次开始: plan_id=%s step_id=%s "
                "batch=%s/%s field_count=%s",
                context.plan_id,
                step.step_id,
                batch_number,
                total_batches,
                len(fields_batch),
            )
            return batch_index, await execute_fields(fields_batch, batch_number, 0)

        tasks = [
            asyncio.create_task(execute_batch(batch_index))
            for batch_index in range(total_batches)
        ]
        try:
            completed_batches = await asyncio.gather(*tasks)
        except FieldMappingBatchError as error:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            logger.error(
                "[BATCH_FAILED] 字段映射原子失败: plan_id=%s step_id=%s batch=%s/%s error_category=%s",
                context.plan_id,
                step.step_id,
                error.batch_number,
                total_batches,
                error.error_code,
            )
            return _failed(step, error.error_code, str(error))

        await _publish_progress(
            context,
            step,
            ProgressPhase.VALIDATION,
            ProgressStatus.RUNNING,
            "field_mapping_validating",
        )
        mapping_rows = [
            row
            for _, batch_rows in sorted(completed_batches, key=lambda item: item[0])
            for row in batch_rows
        ]
        if len(mapping_rows) != len(available_fields):
            return _failed(step, "field_mapping_incomplete", "字段映射结果数量与输入字段数量不一致")

        typed_mappings = tuple(FieldMappingRow.model_validate(row) for row in mapping_rows)
        staged_sub_rule_results = None
        staged_mapped_sub_rules = None
        event_annotation_summary: str | None = None
        event_annotation_rows: tuple = ()
        # 重映射覆盖提示（#126 决策 1）：会话已有映射结果时重新生成会丢弃手动调整
        had_existing_mapped_rules = bool(
            _session_get(context.session, "mapped_sub_rules")
        )
        # 子规则计算可能抛错或原地修改输入，因此必须在 session 副本上完成后再提交。
        sub_rules = copy.deepcopy(_session_get(context.session, "mapped_sub_rules") or [])
        if not sub_rules:
            classification = _session_get(context.session, "log_classification")
            raw_log_lines = _session_get(context.session, "raw_log_lines", []) or []
            if isinstance(classification, dict) and classification:
                from agent.tools.rule_generator import generate_sub_rules

                logs_text = "\n".join(str(line) for line in raw_log_lines)
                sub_rules = generate_sub_rules(classification, all_logs_str=logs_text)
        if sub_rules:
            from agent.tools import load_object_mapping
            from agent.tools.rule_generator.field_mapping import apply_field_mapping_to_sub_rules

            staged_sub_rule_results = []
            for sub_rule in sub_rules:
                rule_fields = {
                    str(item.get("index", ""))
                    for item in sub_rule.get("normalize", []) or []
                    if isinstance(item, dict)
                }
                staged_sub_rule_results.append(
                    {
                        "rule_name": str(sub_rule.get("name", "")),
                        "mappings": [
                            row
                            for row in mapping_rows
                            if str(row.get("原始字段名", "")) in rule_fields
                        ],
                    }
                )
            object_mapping_path = REPO_ROOT / "config" / "对象.xlsx"
            object_loader = self._object_map_loader or load_object_mapping
            object_entity_map = object_loader(str(object_mapping_path))
            staged_mapped_sub_rules = apply_field_mapping_to_sub_rules(
                sub_rules,
                staged_sub_rule_results,
                object_entity_map,
            )
            # 事件名称标注（PRD #124）：映射成功后、原子写回前，对每条子规则
            # 判定【事件名称】并按绑定写入【事件级别】。LLM 失败重试一次，
            # 仍失败整步失败——不静默跳过，保持一次性 session 提交的原子性。
            annotation_outcome = await self._annotate_event_names(
                step, context, staged_mapped_sub_rules
            )
            if isinstance(annotation_outcome, StepResult):
                return annotation_outcome
            (
                staged_mapped_sub_rules,
                event_annotation_summary,
                event_annotation_rows,
            ) = annotation_outcome

        staged_decoded_data = None
        download_kind = None
        download_content = None
        decoded_data = _session_get(context.session, "decoded_data")
        has_decoded_config = (
            "session.decoded_config" in context.session_facts.available_config_refs
        )
        if has_decoded_config and isinstance(decoded_data, (dict, list)) and decoded_data:
            from agent.tools import load_object_mapping
            from agent.tools.rule_generator.field_mapping import apply_field_mapping_to_config

            object_mapping_path = REPO_ROOT / "config" / "对象.xlsx"
            object_loader = self._object_map_loader or load_object_mapping
            object_entity_map = object_loader(str(object_mapping_path))
            staged_decoded_data = apply_field_mapping_to_config(
                copy.deepcopy(decoded_data),
                mapping_rows,
                object_entity_map,
            )
            download_kind = "mapped_config"
            download_content = _build_config_artifact(
                staged_decoded_data,
                len(typed_mappings),
            ).content
            logger.info(
                "[FIELD_MAPPING_FILLED_CONFIG] 回填配置产物已生成: "
                "plan_id=%s step_id=%s root_type=%s content_bytes=%s",
                context.plan_id,
                step.step_id,
                type(staged_decoded_data).__name__,
                len(download_content.encode("utf-8")),
            )
        elif staged_mapped_sub_rules is not None:
            download_kind = "mapped_sub_rules"
            download_content = _build_config_artifact(
                staged_mapped_sub_rules,
                len(typed_mappings),
            ).content
            logger.info(
                "[FIELD_MAPPING_MAPPED_SUB_RULES] 映射后子规则产物已生成: "
                "plan_id=%s step_id=%s rule_count=%s content_bytes=%s",
                context.plan_id,
                step.step_id,
                len(staged_mapped_sub_rules),
                len(download_content.encode("utf-8")),
            )

        # 所有模型批次、类型校验和领域写回计算完成后，才进入一次性 session 提交。
        await _publish_progress(
            context,
            step,
            ProgressPhase.WRITEBACK,
            ProgressStatus.RUNNING,
            "field_mapping_writing",
        )
        _session_set(context.session, "last_mapping_data", mapping_rows)
        if staged_sub_rule_results is not None and staged_mapped_sub_rules is not None:
            _session_set(context.session, "sub_rule_mapping_results", staged_sub_rule_results)
            _session_set(context.session, "mapped_sub_rules", staged_mapped_sub_rules)
        if staged_decoded_data is not None:
            _session_set(context.session, "decoded_data", staged_decoded_data)
        # 区分「唯一字段映射数」与「实际更新的 normalize 项数」（#23）：
        # 同一字段在多条子规则会被更新多次，故更新数 ≥ 唯一映射数。
        updated_normalize_count = 0
        if staged_mapped_sub_rules is not None:
            updated_normalize_count += max(
                0, _count_tagged_normalize(staged_mapped_sub_rules) - _count_tagged_normalize(sub_rules)
            )
        if staged_decoded_data is not None:
            updated_normalize_count += max(
                0, _count_tagged_normalize(staged_decoded_data) - _count_tagged_normalize(decoded_data)
            )
        logger.info(
            "[FIELD_MAPPING_WRITEBACK] plan_id=%s step_id=%s 唯一字段映射数=%s "
            "实际更新normalize项数=%s",
            context.plan_id,
            step.step_id,
            len(typed_mappings),
            updated_normalize_count,
        )
        message = (
            f"字段映射完成：唯一字段 {len(typed_mappings)} 项，"
            f"实际更新 {updated_normalize_count} 个 normalize 项"
        )
        if event_annotation_summary:
            message = f"{message}；{event_annotation_summary}"
        if had_existing_mapped_rules and staged_mapped_sub_rules is not None:
            message = (
                f"{message}；⚠️ 重新映射已重新生成子规则，"
                "此前手动调整（字段增删/事件名称修改）已被覆盖"
            )
        return _success(
            step,
            FieldMappingArtifact(
                mappings=typed_mappings,
                item_count=len(typed_mappings),
                event_annotations=event_annotation_rows,
                download_kind=download_kind,
                download_content=download_content,
            ),
            message=message,
        )

    async def _annotate_event_names(
        self,
        step: FieldMappingStep,
        context: ExecutionContext,
        mapped_sub_rules: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], str | None, tuple] | StepResult:
        """判定并写入每条子规则的【事件名称】+ 绑定【事件级别】。

        成功返回 (标注后的子规则, 摘要, 标注明细行)；LLM 可重试错误重试
        一次，仍失败返回 failed StepResult（调用方立即返回，session 不提交）。
        待人工确认的子规则保持不变，明细行 status=uncertain。
        """
        from agent.shared import event_classify

        judgments: dict[str, str] = {}
        uncertain: list[str] = []
        for attempt in range(2):
            try:
                judgments, uncertain = await event_classify.classify_sub_rule_events(
                    mapped_sub_rules,
                    llm_client=self._event_classifier,
                )
                break
            except Exception as error:  # noqa: BLE001 - 适配层统一判定可重试性
                if attempt == 0 and _is_retriable_model_error(error):
                    await asyncio.sleep(
                        _retry_delay_seconds(error, self._mapping_policy.retry_delay_seconds)
                    )
                    continue
                logger.warning(
                    "[EVENT_NAME_ANNOTATE] 判定失败: plan_id=%s step_id=%s error=%s",
                    context.plan_id,
                    step.step_id,
                    error,
                )
                return _failed(step, "event_classify_failed", "事件名称判定失败，请重试")

        annotated = event_classify.apply_event_fields_to_sub_rules(mapped_sub_rules, judgments)
        if not judgments and not uncertain:
            # 无可判定子规则时不改数据、不向消息追加噪音
            return mapped_sub_rules, "", ()
        threat_count = sum(
            1 for value in judgments.values() if value in event_classify.THREAT_EVENT_NAMES
        )
        summary = (
            f"事件名称已标注 {len(judgments)} 条（威胁 {threat_count}、"
            f"非威胁 {len(judgments) - threat_count}）"
        )
        if uncertain:
            summary += f"；待人工确认 {len(uncertain)} 条（{'、'.join(uncertain)}）"
        logger.info(
            "[EVENT_NAME_ANNOTATE] plan_id=%s step_id=%s judged=%s uncertain=%s",
            context.plan_id,
            step.step_id,
            len(judgments),
            len(uncertain),
        )
        from contracts.planner_models import EventAnnotationRow

        annotation_rows: list[EventAnnotationRow] = []
        uncertain_set = set(uncertain)
        for rule in mapped_sub_rules:
            rule_name = str(rule.get("name", ""))
            event_name = judgments.get(rule_name, "")
            if event_name:
                annotation_rows.append(
                    EventAnnotationRow(
                        rule_name=rule_name,
                        event_name=event_name,
                        event_level=event_classify.EVENT_NAME_LEVEL_BINDING[event_name],
                        status="judged",
                    )
                )
            elif rule_name in uncertain_set:
                annotation_rows.append(
                    EventAnnotationRow(rule_name=rule_name, status="uncertain")
                )
        return annotated, summary or None, tuple(annotation_rows)
