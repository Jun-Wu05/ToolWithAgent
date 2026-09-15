"""Chainlit 自然语言入口：适配输入、调用 Planner/Executor 并渲染一次结果。"""

from __future__ import annotations

from typing import Any
import uuid

import chainlit as cl

from application.request_runtime import (
    clear_session_data,
    is_explicit_clear_command,
    run_user_request,
)
from application.session_projection import build_session_facts
from contracts.planner_models import ExecutionReport
from web.chainlit_progress import get_session_progress_sink, reset_session_progress_sink
from web.plan_renderer import (
    clear_primary_report_anchor,
    refresh_primary_report_anchor,
    render_decision,
    render_execution_report,
)


async def handle_user_message(user_session: Any, team: Any, user_text: str) -> None:
    """处理一条用户指令；所有自然语言业务请求恰好调用 Planner 一次。

    参数：
        user_session: 当前结构化会话状态。
        team: 仅供执行适配器调用已选定的专业 Agent。
        user_text: 未改写的用户原文。

    不变量：
        Planner 返回前不调用任何业务执行器；Planner 失败或要求澄清时不执行。

    错误模式：
        规划错误由 Planner 转为安全追问；步骤错误由 ExecutionReport 返回稳定错误码。
    """
    if is_explicit_clear_command(user_text):
        await _clear_session_data(user_session)
        await reset_session_progress_sink()
        return

    progress_plan_id = f"request-{uuid.uuid4().hex[:12]}"
    progress_ledger = get_session_progress_sink()
    progress_sink = progress_ledger.begin_request()

    try:
        result = await run_user_request(
            session=user_session,
            team=team,
            user_text=user_text,
            progress_sink=progress_sink,
            progress_plan_id=progress_plan_id,
        )
        session_facts = build_session_facts(user_session)
        if isinstance(result, ExecutionReport):
            final_config = (
                user_session.mapped_sub_rules
                if hasattr(user_session, "mapped_sub_rules")
                else user_session.get("mapped_sub_rules")
            )
            await refresh_primary_report_anchor(result, final_config)
            await render_execution_report(result, session_facts=session_facts)
        else:
            await render_decision(result, session_facts=session_facts)
    finally:
        # UI 或执行器异常都必须停止心跳，避免请求结束后仍更新旧任务。
        await progress_ledger.finish_request(progress_sink)

async def _clear_session_data(user_session: Any) -> None:
    """执行确定性清空事件，并只保留统一的完成提示。"""
    clear_session_data(user_session)
    clear_primary_report_anchor()
    await cl.Message(content="🗑️ **数据已清空** — 请上传新文件继续处理。").send()
