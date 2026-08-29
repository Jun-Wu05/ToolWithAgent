"""威胁映射适配器及已迁移专业操作的兼容委托。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from agent.shared.logger import get_logger

from application.adapters.log_parse import LogParseAdapter
from application.adapters.field_mapping import FieldMappingAdapter, FieldMappingExecutionPolicy
from application.adapters.enum_extract import EnumExtractAdapter
from application.execution import ExecutionContext
from contracts.planner_models import (
    EnumExtractStep,
    EnumValuesArtifact,
    FieldMappingStep,
    LogParseStep,
    StepResult,
    StepSpec,
    ThreatMappingArtifact,
    ThreatMappingRow,
    ThreatMappingStep,
)
from contracts.session_artifacts import EnumArtifactSlot, ThreatArtifactSlot
from application.adapters.shared import (
    _failed,
    _needs_input,
    _session_get,
    _session_set,
    _success,
    run_member_stream,
)


logger = get_logger("execution_adapters")


class ProfessionalAgentAdapter:
    """直接调用已选定专业 Agent 或领域 Pipeline，不承担意图理解与界面渲染。"""

    def __init__(
        self,
        team: Any,
        mapping_policy: FieldMappingExecutionPolicy | None = None,
        candidate_retriever: Any | None = None,
        object_map_loader: Any | None = None,
        event_classifier: Any | None = None,
    ) -> None:
        """保存专业 Agent 注册表、字段映射执行策略与可注入依赖（Issue #88 接缝）。"""
        self._team = team
        self._mapping_policy = mapping_policy or FieldMappingExecutionPolicy()
        self._log_parse_adapter = LogParseAdapter()
        self._enum_extract_adapter = EnumExtractAdapter()
        self._field_mapping_adapter = FieldMappingAdapter(
            team,
            mapping_policy,
            candidate_retriever=candidate_retriever,
            object_map_loader=object_map_loader,
            event_classifier=event_classifier,
        )

    async def execute(
        self,
        step: StepSpec,
        context: ExecutionContext,
        dependencies: Mapping[str, StepResult],
    ) -> StepResult:
        """执行日志、枚举、字段或威胁操作，并返回类型化产物。"""
        if isinstance(step, LogParseStep):
            return await self._log_parse_adapter.execute(step, context, dependencies)
        if isinstance(step, EnumExtractStep):
            return await self._enum_extract_adapter.execute(step, context, dependencies)
        if isinstance(step, FieldMappingStep):
            return await self._field_mapping_adapter.execute(step, context, dependencies)
        if isinstance(step, ThreatMappingStep):
            return await self._execute_threat_mapping(step, context, dependencies)
        raise TypeError(f"ProfessionalAgentAdapter 不支持步骤类型: {step.type}")

    async def _execute_threat_mapping(
        self,
        step: ThreatMappingStep,
        context: ExecutionContext,
        dependencies: Mapping[str, StepResult],
    ) -> StepResult:
        """只使用显式值或本次依赖的枚举产物调用威胁映射 Agent。"""
        from web.parsers import parse_json_threat_result

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
        content = await self._run_member("ThreatAgent", model_input)
        mapping_rows = parse_json_threat_result(content)
        if not mapping_rows:
            return _failed(step, "threat_mapping_empty", "威胁映射未生成有效结果")
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

    async def _run_member(
        self,
        member_name: str,
        model_input: str,
        *,
        plan_id: str = "pending",
        step_id: str = "pending",
        batch_number: int | None = None,
    ) -> Any:
        """消费专业 Agent 事件流，只接收完成事件内容并记录安全 token 计数。"""
        return await run_member_stream(
            self._team,
            member_name,
            model_input,
            plan_id=plan_id,
            step_id=step_id,
            batch_number=batch_number,
        )
