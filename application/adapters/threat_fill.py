"""威胁映射填充 Application StepAdapter。"""

from __future__ import annotations

from collections.abc import Mapping

from agent.shared.logger import get_logger
from agent.shared.mapping_utils import apply_fill_to_config, count_field_mappings
from application.adapters.fill_shared import unbind_fixed_field_bindings
from application.adapters.shared import (
    _build_config_artifact,
    _failed,
    _is_enum_config_stale,
    _needs_input,
    _read_config,
    _session_get,
    _write_config,
)
from application.artifact_targets import collect_standard_fields, resolve_standard_target
from application.execution import ExecutionContext
from contracts.planner_models import (
    FillStep,
    StepResult,
    StepSpec,
    StepStatus,
    ThreatMappingArtifact,
)
from contracts.session_artifacts import ThreatArtifactSlot


logger = get_logger("execution_adapters")


class ThreatFillAdapter:
    """只消费声明的威胁映射产物并写回显式配置来源。"""

    async def execute(
        self,
        step: StepSpec,
        context: ExecutionContext,
        dependencies: Mapping[str, StepResult],
    ) -> StepResult:
        """执行威胁填充；依赖、血缘或配置来源不匹配时快速失败。"""
        if not isinstance(step, FillStep) or step.fill_kind != "threat":
            raise TypeError("ThreatFillAdapter 只接受 threat FillStep")
        if _is_enum_config_stale(context.session, step.config_ref):
            return _needs_input(
                step,
                "enum_refill_required",
                "枚举映射附件已更新，请先重新执行枚举填充",
            )

        if step.source_ref == "session.artifacts.threat_mapping":
            raw_slot = _session_get(context.session, "latest_threat_artifact")
            try:
                slot = (
                    raw_slot
                    if isinstance(raw_slot, ThreatArtifactSlot)
                    else ThreatArtifactSlot.model_validate(raw_slot)
                )
            except (TypeError, ValueError):
                return _needs_input(
                    step,
                    "artifact_source_unavailable",
                    "最近威胁映射产物已不可用，请重新执行威胁映射",
                )
            artifact = slot.artifact
            current_config = _read_config(context.session, step.config_ref)
            if artifact.source_field:
                expected_target = resolve_standard_target(current_config, artifact.source_field)
                if expected_target is None:
                    return _needs_input(
                        step,
                        "artifact_target_unavailable",
                        "最近威胁映射的来源字段没有唯一可填充标准字段",
                    )
                if step.target_fields != (expected_target,):
                    return _needs_input(
                        step,
                        "artifact_target_mismatch",
                        f"最近威胁映射只能填回标准字段: {expected_target}",
                    )
            else:
                available_targets = set(collect_standard_fields(current_config))
                if step.target_fields[0] not in available_targets:
                    return _needs_input(
                        step,
                        "artifact_target_unavailable",
                        "指定字段不是当前配置中的可填充标准字段",
                    )
        else:
            dependency_id = step.source_ref.removeprefix("step:")
            dependency = dependencies.get(dependency_id)
            if dependency is None or dependency.artifact is None:
                return _failed(step, "dependency_missing", "威胁填充缺少声明的映射产物")
            if not isinstance(dependency.artifact, ThreatMappingArtifact):
                return _failed(step, "dependency_type_mismatch", "依赖产物不是威胁映射")
            artifact = dependency.artifact

        current_config = _read_config(context.session, step.config_ref)
        current_config, unbind_note = unbind_fixed_field_bindings(
            current_config, step.target_fields
        )
        mapping_rows = [row.model_dump(by_alias=True) for row in artifact.mappings]
        if not mapping_rows:
            return _failed(step, "threat_mapping_empty", "威胁映射产物为空")

        before_count = count_field_mappings(current_config, step.target_fields)
        updated_config = current_config
        for target_field in step.target_fields:
            updated_config = apply_fill_to_config(updated_config, mapping_rows, target_field)
        after_count = count_field_mappings(updated_config, step.target_fields)
        _write_config(context.session, step.config_ref, updated_config)
        changed_count = max(0, after_count - before_count)
        logger.info(
            "[THREAT_FILL] 填充完成: step_id=%s config_ref=%s target_field_count=%s "
            "mapping_rule_count=%s before_count=%s after_count=%s changed_count=%s",
            step.step_id,
            step.config_ref,
            len(step.target_fields),
            len(mapping_rows),
            before_count,
            after_count,
            changed_count,
        )
        return StepResult(
            step_id=step.step_id,
            operation_type=step.type,
            status=StepStatus.SUCCESS,
            changed_count=changed_count,
            artifact=_build_config_artifact(
                updated_config, after_count, "threatmapping_config"
            ),
            message="威胁映射已填充到目标字段" + unbind_note,
        )
