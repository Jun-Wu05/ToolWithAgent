"""字段映射适配器：编排批处理结果、领域产物与原子会话写回。"""

from __future__ import annotations

import asyncio
import copy
from collections.abc import Mapping
from typing import Any

from agent.shared.logger import get_logger
from application.adapters.shared import (
    REPO_ROOT, _build_config_artifact, _count_tagged_normalize, _failed,
    _is_retriable_model_error, _publish_progress, _retry_delay_seconds,
    _session_get, _session_set, _success,
)
from application.execution import ExecutionContext
from application.field_mapping_batch import (
    FieldMappingBatchError, FieldMappingBatchRunner, FieldMappingExecutionPolicy,
)
from contracts.progress import ProgressPhase, ProgressStatus
from contracts.planner_models import (
    FieldMappingArtifact, FieldMappingRow, FieldMappingStep, StepResult, StepStatus,
)

logger = get_logger("execution_adapters")


class FieldMappingAdapter:
    """连接 StepSpec、批处理 Runner、领域产物与 Session 原子提交。"""

    def __init__(
        self,
        team: Any,
        mapping_policy: FieldMappingExecutionPolicy | None = None,
        candidate_retriever: Any | None = None,
        object_map_loader: Any | None = None,
        event_classifier: Any | None = None,
        batch_runner: Any | None = None,
    ) -> None:
        """保存批处理 Runner、执行策略及领域服务接缝。"""
        self._mapping_policy = mapping_policy or FieldMappingExecutionPolicy()
        self._object_map_loader = object_map_loader
        self._event_classifier = event_classifier
        self._batch_runner = (
            batch_runner
            if batch_runner is not None
            else FieldMappingBatchRunner(
                team,
                policy=self._mapping_policy,
                candidate_retriever=candidate_retriever,
            )
        )

    async def execute(
        self,
        step: FieldMappingStep,
        context: ExecutionContext,
        dependencies: Mapping[str, StepResult] | None = None,
    ) -> StepResult:
        """校验步骤类型并执行字段映射。"""
        if not isinstance(step, FieldMappingStep):
            raise TypeError("FieldMappingAdapter 只接受 FieldMappingStep")
        return await self._execute_field_mapping(step, context)

    async def _execute_field_mapping(
        self, step: FieldMappingStep, context: ExecutionContext
    ) -> StepResult:
        """运行批处理，验证完整结果，再计算产物并一次性提交 Session。"""
        mappable_fields = list(context.session_facts.mappable_fields)
        if (
            not mappable_fields
            and context.session_facts.has_decoded_config
            and context.session_facts.decoded_mapped_field_count > 0
            and context.session_facts.decoded_unmapped_field_count == 0
        ):
            skipped_count = context.session_facts.decoded_mapped_field_count
            return StepResult(
                step_id=step.step_id,
                operation_type=step.type,
                status=StepStatus.SUCCESS,
                message=(
                    "所有字段均已映射，无需再次执行；"
                    f"跳过已映射 {skipped_count} 个（保留原映射）"
                ),
            )
        simplified_data = _session_get(context.session, "simplified_data", {}) or {}
        original_log_sample = (
            simplified_data.get("original_log_sample", "")
            if isinstance(simplified_data, Mapping) else ""
        )

        async def publish_batch_progress(
            phase: ProgressPhase, status: ProgressStatus, message_code: str, **details: Any
        ) -> None:
            """把 Runner 的批次进度绑定到当前计划与步骤。"""
            await _publish_progress(context, step, phase, status, message_code, **details)

        try:
            mapping_rows = await self._batch_runner.run(
                mappable_fields,
                original_log_sample=original_log_sample,
                plan_id=context.plan_id,
                step_id=step.step_id,
                publish_progress=publish_batch_progress,
            )
        except FieldMappingBatchError as error:
            logger.error(
                "[BATCH_FAILED] 字段映射原子失败: plan_id=%s step_id=%s "
                "batch=%s error_category=%s",
                context.plan_id, step.step_id, error.batch_number, error.error_code,
            )
            return _failed(step, error.error_code, str(error))

        await _publish_progress(
            context, step, ProgressPhase.VALIDATION, ProgressStatus.RUNNING,
            "field_mapping_validating",
        )
        if len(mapping_rows) != len(mappable_fields):
            return _failed(step, "field_mapping_incomplete", "字段映射结果数量与输入字段数量不一致")

        typed_mappings = tuple(FieldMappingRow.model_validate(row) for row in mapping_rows)
        staged_sub_rule_results = None
        staged_mapped_sub_rules = None
        event_annotation_summary: str | None = None
        event_annotation_rows: tuple = ()
        had_existing_mapped_rules = bool(_session_get(context.session, "mapped_sub_rules"))
        sub_rules = copy.deepcopy(_session_get(context.session, "mapped_sub_rules") or [])
        if not sub_rules:
            classification = _session_get(context.session, "log_classification")
            raw_log_lines = _session_get(context.session, "raw_log_lines", []) or []
            if isinstance(classification, dict) and classification:
                from agent.tools.rule_generator import generate_sub_rules
                sub_rules = generate_sub_rules(
                    classification, all_logs_str="\n".join(str(line) for line in raw_log_lines)
                )
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
                staged_sub_rule_results.append({
                    "rule_name": str(sub_rule.get("name", "")),
                    "mappings": [
                        row for row in mapping_rows
                        if str(row.get("原始字段名", "")) in rule_fields
                    ],
                })
            object_loader = self._object_map_loader or load_object_mapping
            object_entity_map = object_loader(str(REPO_ROOT / "config" / "对象.xlsx"))
            staged_mapped_sub_rules = apply_field_mapping_to_sub_rules(
                sub_rules, staged_sub_rule_results, object_entity_map
            )
            annotation_outcome = await self._annotate_event_names(
                step, context, staged_mapped_sub_rules
            )
            if isinstance(annotation_outcome, StepResult):
                return annotation_outcome
            staged_mapped_sub_rules, event_annotation_summary, event_annotation_rows = (
                annotation_outcome
            )

        staged_decoded_data = None
        download_kind = None
        download_content = None
        decoded_data = _session_get(context.session, "decoded_data")
        has_decoded_config = "session.decoded_config" in context.session_facts.available_config_refs
        if has_decoded_config and isinstance(decoded_data, (dict, list)) and decoded_data:
            from agent.tools import load_object_mapping
            from agent.tools.rule_generator.field_mapping import apply_field_mapping_to_config

            object_loader = self._object_map_loader or load_object_mapping
            object_entity_map = object_loader(str(REPO_ROOT / "config" / "对象.xlsx"))
            staged_decoded_data = apply_field_mapping_to_config(
                copy.deepcopy(decoded_data), mapping_rows, object_entity_map
            )
            download_kind = "mapped_config"
            download_content = _build_config_artifact(
                staged_decoded_data, len(typed_mappings)
            ).content
            logger.info(
                "[FIELD_MAPPING_FILLED_CONFIG] 回填配置产物已生成: "
                "plan_id=%s step_id=%s root_type=%s content_bytes=%s",
                context.plan_id, step.step_id, type(staged_decoded_data).__name__,
                len(download_content.encode("utf-8")),
            )
        elif staged_mapped_sub_rules is not None:
            download_kind = "mapped_sub_rules"
            download_content = _build_config_artifact(
                staged_mapped_sub_rules, len(typed_mappings)
            ).content
            logger.info(
                "[FIELD_MAPPING_MAPPED_SUB_RULES] 映射后子规则产物已生成: "
                "plan_id=%s step_id=%s rule_count=%s content_bytes=%s",
                context.plan_id, step.step_id, len(staged_mapped_sub_rules),
                len(download_content.encode("utf-8")),
            )

        await _publish_progress(
            context, step, ProgressPhase.WRITEBACK, ProgressStatus.RUNNING,
            "field_mapping_writing",
        )
        _session_set(context.session, "last_mapping_data", mapping_rows)
        if staged_sub_rule_results is not None and staged_mapped_sub_rules is not None:
            _session_set(context.session, "sub_rule_mapping_results", staged_sub_rule_results)
            _session_set(context.session, "mapped_sub_rules", staged_mapped_sub_rules)
        if staged_decoded_data is not None:
            _session_set(context.session, "decoded_data", staged_decoded_data)

        updated_normalize_count = 0
        decoded_added_count = 0
        if staged_mapped_sub_rules is not None:
            updated_normalize_count += max(
                0, _count_tagged_normalize(staged_mapped_sub_rules)
                - _count_tagged_normalize(sub_rules)
            )
        if staged_decoded_data is not None:
            decoded_added_count = max(
                0, _count_tagged_normalize(staged_decoded_data)
                - _count_tagged_normalize(decoded_data)
            )
            updated_normalize_count += decoded_added_count
        logger.info(
            "[FIELD_MAPPING_WRITEBACK] plan_id=%s step_id=%s 唯一字段映射数=%s "
            "实际更新normalize项数=%s",
            context.plan_id, step.step_id, len(typed_mappings), updated_normalize_count,
        )
        message = (
            f"字段映射完成：唯一字段 {len(typed_mappings)} 项，"
            f"实际更新 {updated_normalize_count} 个 normalize 项"
        )
        if staged_decoded_data is not None:
            message = (
                f"{message}；上传规则新增映射 {decoded_added_count} 个 / "
                f"跳过已映射 {context.session_facts.decoded_mapped_field_count} 个"
                "（保留原映射）"
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
                mappings=typed_mappings, item_count=len(typed_mappings),
                event_annotations=event_annotation_rows, download_kind=download_kind,
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
        """判定并写入每条子规则的事件名称和绑定事件级别。"""
        from agent.shared import event_classify

        judgments: dict[str, str] = {}
        uncertain: list[str] = []
        for attempt in range(2):
            try:
                judgments, uncertain = await event_classify.classify_sub_rule_events(
                    mapped_sub_rules, llm_client=self._event_classifier
                )
                break
            except Exception as error:  # noqa: BLE001 - 适配层统一判定可重试错误
                if attempt == 0 and _is_retriable_model_error(error):
                    await asyncio.sleep(
                        _retry_delay_seconds(error, self._mapping_policy.retry_delay_seconds)
                    )
                    continue
                logger.warning(
                    "[EVENT_NAME_ANNOTATE] 判定失败: plan_id=%s step_id=%s error=%s",
                    context.plan_id, step.step_id, error,
                )
                return _failed(step, "event_classify_failed", "事件名称判定失败，请重试")

        annotated = event_classify.apply_event_fields_to_sub_rules(mapped_sub_rules, judgments)
        if not judgments and not uncertain:
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
            context.plan_id, step.step_id, len(judgments), len(uncertain),
        )
        from contracts.planner_models import EventAnnotationRow

        annotation_rows: list[EventAnnotationRow] = []
        uncertain_set = set(uncertain)
        for rule in mapped_sub_rules:
            rule_name = str(rule.get("name", ""))
            event_name = judgments.get(rule_name, "")
            if event_name:
                annotation_rows.append(EventAnnotationRow(
                    rule_name=rule_name, event_name=event_name,
                    event_level=event_classify.EVENT_NAME_LEVEL_BINDING[event_name],
                    status="judged",
                ))
            elif rule_name in uncertain_set:
                annotation_rows.append(EventAnnotationRow(rule_name=rule_name, status="uncertain"))
        return annotated, summary or None, tuple(annotation_rows)


__all__ = ["FieldMappingAdapter", "FieldMappingBatchError", "FieldMappingExecutionPolicy"]
