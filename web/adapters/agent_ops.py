"""威胁映射适配器及已迁移专业操作的兼容委托。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agent.shared.logger import get_logger

from application.adapters.log_parse import LogParseAdapter
from application.adapters.field_mapping import FieldMappingAdapter, FieldMappingExecutionPolicy
from application.adapters.enum_extract import EnumExtractAdapter
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
from application.adapters.shared import (
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
        """执行日志、枚举、字段或威胁操作，并返回类型化产物。"""
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
        """消费专业 Agent 事件流，只接收完成事件内容并记录安全 token 计数。"""
        return await run_member_stream(
            self._team,
            member_name,
            model_input,
            plan_id=plan_id,
            step_id=step_id,
            batch_number=batch_number,
        )
