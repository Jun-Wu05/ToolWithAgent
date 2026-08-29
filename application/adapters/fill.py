"""按类型化 fill_kind 分派 Application 填充适配器。"""

from __future__ import annotations

from collections.abc import Mapping

from application.adapters.enum_fill import EnumFillAdapter
from application.adapters.threat_fill import ThreatFillAdapter
from application.execution import ExecutionContext
from contracts.planner_models import FillStep, StepResult, StepSpec


class FillAdapter:
    """只根据 FillStep.fill_kind 分派，不从文本或 Session 猜测类型。"""

    def __init__(
        self,
        enum_adapter: EnumFillAdapter | None = None,
        threat_adapter: ThreatFillAdapter | None = None,
    ) -> None:
        self._enum_adapter = enum_adapter or EnumFillAdapter()
        self._threat_adapter = threat_adapter or ThreatFillAdapter()

    async def execute(
        self,
        step: StepSpec,
        context: ExecutionContext,
        dependencies: Mapping[str, StepResult],
    ) -> StepResult:
        if not isinstance(step, FillStep):
            raise TypeError("FillAdapter 只接受 FillStep")
        if step.fill_kind == "enum":
            return await self._enum_adapter.execute(step, context, dependencies)
        return await self._threat_adapter.execute(step, context, dependencies)
