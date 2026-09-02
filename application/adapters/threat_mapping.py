"""威胁类型映射 Application StepAdapter。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from agent.shared.logger import get_logger
from application.adapters.shared import (
    _failed,
    _needs_input,
    _session_get,
    _session_set,
    _success,
    run_member_stream,
)
from application.execution import ExecutionContext
from application.parsing import parse_json_threat_result
from application.threat_chain_policy import ensure_threat_mapping_coverage
from contracts.planner_models import (
    EnumValuesArtifact,
    StepResult,
    StepSpec,
    ThreatMappingArtifact,
    ThreatMappingRow,
    ThreatMappingStep,
)
from contracts.session_artifacts import EnumArtifactSlot, ThreatArtifactSlot

logger = get_logger("execution_adapters")


class ThreatMappingAdapter:
    """从显式枚举来源生成威胁映射并提交可引用会话产物。"""

    def __init__(self, team: Any) -> None:
        self._team = team

    async def execute(
        self,
        step: StepSpec,
        context: ExecutionContext,
        dependencies: Mapping[str, StepResult],
    ) -> StepResult:
        """只消费声明来源，调用一次 ThreatAgent，并在成功后提交双槽。"""
        if not isinstance(step, ThreatMappingStep):
            raise TypeError("ThreatMappingAdapter 只接受 ThreatMappingStep")

        source_field: str | None = None
        if step.source_ref == "user.values":
            values = list(step.values)
        elif step.source_ref == "session.artifacts.enum_values":
            raw_slot = _session_get(context.session, "latest_enum_artifact")
            try:
                slot = (
                    raw_slot
                    if isinstance(raw_slot, EnumArtifactSlot)
                    else EnumArtifactSlot.model_validate(raw_slot)
                )
            except (TypeError, ValueError):
                return _needs_input(
                    step,
                    "artifact_source_unavailable",
                    "最近枚举值产物已不可用，请重新提取枚举值",
                )
            values = list(slot.artifact.values)
            source_field = slot.source_field
        else:
            dependency_id = step.source_ref.removeprefix("step:")
            dependency = dependencies.get(dependency_id)
            artifact = dependency.artifact if dependency else None
            if not isinstance(artifact, EnumValuesArtifact):
                return _failed(step, "dependency_type_mismatch", "依赖产物不是枚举值")
            values = list(artifact.values)
            source_field = artifact.field or None

        model_input = json.dumps({"values": values}, ensure_ascii=False)
        content = await run_member_stream(self._team, "ThreatAgent", model_input)
        mapping_rows = parse_json_threat_result(content)
        if not mapping_rows:
            return _failed(step, "threat_mapping_empty", "威胁映射未生成有效结果")
        # 值全覆盖兜底（#173 决策 5）：未被任何映射行覆盖的提取值确定性补
        # 「其他」兜底行，不依赖提示词自觉；跨轮/手输路径同样受益。
        rows_before = len(mapping_rows)
        mapping_rows = ensure_threat_mapping_coverage(values, mapping_rows)
        appended = len(mapping_rows) - rows_before
        if appended:
            logger.info(
                "[THREAT_MAPPING] 全覆盖兜底补行: value_count=%s "
                "row_count=%s->%s appended=%s",
                len(values),
                rows_before,
                len(mapping_rows),
                appended,
            )

        typed_mappings = tuple(ThreatMappingRow.model_validate(row) for row in mapping_rows)
        artifact = ThreatMappingArtifact(
            mappings=typed_mappings,
            item_count=len(typed_mappings),
            source_field=source_field,
        )
        _session_set(context.session, "last_threat_data", mapping_rows)
        _session_set(
            context.session,
            "latest_threat_artifact",
            ThreatArtifactSlot(artifact=artifact, source_field=source_field),
        )
        return _success(step, artifact)
