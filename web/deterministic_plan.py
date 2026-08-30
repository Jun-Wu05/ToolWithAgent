"""把按钮等确定性事件转换为类型化计划并复用统一执行器。"""

from __future__ import annotations

from typing import Any, Sequence

from web.chainlit_progress import get_session_progress_sink
from application.request_runtime import run_deterministic_plan
from web.plan_renderer import render_execution_report
from contracts.planner_models import PlanDecision, StepSpec


async def execute_deterministic_plan(
    user_session: Any,
    team: Any,
    plan_id: str,
    steps: Sequence[StepSpec],
) -> None:
    """执行确定性事件生成的计划；事件适配层必须事先提供全部参数。"""
    decision = PlanDecision(decision="execute", plan_id=plan_id, steps=tuple(steps))
    progress_ledger = get_session_progress_sink()
    progress_sink = progress_ledger.begin_request()
    try:
        report = await run_deterministic_plan(
            session=user_session,
            team=team,
            plan=decision,
            progress_sink=progress_sink,
        )
        await render_execution_report(report)
    finally:
        # 按钮执行异常时也必须停止心跳，避免旧任务继续更新界面。
        await progress_ledger.finish_request(progress_sink)
