"""把按钮等确定性事件转换为类型化计划并复用统一执行器。"""

from __future__ import annotations

from typing import Any, Sequence

from web.chainlit_progress import get_session_progress_sink
from application.request_runtime import run_deterministic_plan
from application.session_projection import build_session_facts
from web.plan_renderer import (
    remember_primary_report,
    render_execution_report,
    update_execution_report_message,
)
from contracts.planner_models import (
    DeterministicPlan,
    ExecutableStep,
    ExecutionReport,
    StepStatus,
)


async def execute_deterministic_plan(
    user_session: Any,
    team: Any,
    plan_id: str,
    steps: Sequence[ExecutableStep],
) -> ExecutionReport:
    """执行确定性事件生成的计划；事件适配层必须事先提供全部参数。"""
    decision = DeterministicPlan(plan_id=plan_id, steps=tuple(steps))
    progress_ledger = get_session_progress_sink()
    progress_sink = progress_ledger.begin_request()
    primary_result_count = 0
    primary_message = None

    async def render_primary(report: ExecutionReport) -> None:
        """在威胁链续跑前渲染主报告并记录其结果边界。"""
        nonlocal primary_result_count, primary_message
        primary_result_count = len(report.results)
        primary_message = await render_execution_report(
            report,
            threat_pending=True,
            session_facts=build_session_facts(user_session),
        )

    try:
        report = await run_deterministic_plan(
            session=user_session,
            team=team,
            plan=decision,
            progress_sink=progress_sink,
            on_primary_report=render_primary,
        )
        final_primary = ExecutionReport(
            plan_id=report.plan_id,
            results=report.results[:primary_result_count],
        )
        if primary_message is not None:
            if final_primary.status != StepStatus.NEEDS_INPUT:
                await update_execution_report_message(primary_message, final_primary)
            remember_primary_report(primary_message, final_primary)
        follow_up_results = report.results[primary_result_count:]
        if follow_up_results:
            await render_execution_report(
                ExecutionReport(plan_id=report.plan_id, results=follow_up_results),
                session_facts=build_session_facts(user_session),
            )
        return report
    finally:
        # 按钮执行异常时也必须停止心跳，避免旧任务继续更新界面。
        await progress_ledger.finish_request(progress_sink)
