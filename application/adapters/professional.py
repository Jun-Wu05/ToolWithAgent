"""供多类专业步骤调用方使用的 Application 组合适配器。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from application.adapters.enum_extract import EnumExtractAdapter
from application.adapters.field_mapping import FieldMappingAdapter, FieldMappingExecutionPolicy
from application.adapters.log_parse import LogParseAdapter
from application.adapters.shared import run_member_stream
from application.adapters.threat_mapping import ThreatMappingAdapter
from application.execution import ExecutionContext
from contracts.planner_models import (
    EnumExtractStep,
    FieldMappingStep,
    LogParseStep,
    StepResult,
    StepSpec,
    ThreatMappingStep,
)


class ProfessionalAgentAdapter:
    """把兼容的专业步骤分派给各自聚焦的 Application 适配器。"""

    def __init__(
        self,
        team: Any,
        mapping_policy: FieldMappingExecutionPolicy | None = None,
        candidate_retriever: Any | None = None,
        object_map_loader: Any | None = None,
        event_classifier: Any | None = None,
    ) -> None:
        """创建日志、枚举、字段与威胁适配器并保存 Team。"""
        self._team = team
        self._log_parse_adapter = LogParseAdapter()
        self._enum_extract_adapter = EnumExtractAdapter()
        self._threat_mapping_adapter = ThreatMappingAdapter(team)
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
        """按类型把步骤分派给唯一的聚焦适配器。"""
        if isinstance(step, LogParseStep):
            return await self._log_parse_adapter.execute(step, context, dependencies)
        if isinstance(step, EnumExtractStep):
            return await self._enum_extract_adapter.execute(step, context, dependencies)
        if isinstance(step, FieldMappingStep):
            return await self._field_mapping_adapter.execute(step, context, dependencies)
        if isinstance(step, ThreatMappingStep):
            return await self._threat_mapping_adapter.execute(step, context, dependencies)
        raise TypeError(f"ProfessionalAgentAdapter 不支持步骤类型: {step.type}")

    async def _run_member(
        self,
        member_name: str,
        model_input: str,
        *,
        plan_id: str = "pending",
        step_id: str = "pending",
        batch_number: int | None = None,
    ) -> Any:
        """消费指定专业 Agent 的事件流并返回完成内容。"""
        return await run_member_stream(
            self._team,
            member_name,
            model_input,
            plan_id=plan_id,
            step_id=step_id,
            batch_number=batch_number,
        )
