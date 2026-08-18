"""Chainlit 自然语言入口：适配输入、调用 Planner/Executor 并渲染一次结果。"""

from __future__ import annotations

from typing import Any
import uuid

import chainlit as cl

from agent.core.planner import PlannerService
from agent.shared.logger import get_logger
from web.chainlit_progress import get_session_progress_sink, reset_session_progress_sink
from web.execution_adapters import create_default_adapters
from web.history_store import append_history
from web.plan_executor import ExecutionContext, PlanExecutor
from web.plan_renderer import render_decision, render_execution_report
from contracts.planner_models import ConversationTurn
from contracts.progress import ProgressEvent, ProgressPhase, ProgressStatus
from contracts.session_facts import build_session_facts

logger = get_logger("user_message_handlers")


# 只有完整匹配的明确命令才可绕过 Planner，避免普通句子包含“新建”等词时误清空。
_CLEAR_COMMANDS = {
    "清空",
    "清空数据",
    "清除数据",
    "切换数据",
    "换文件",
    "重新上传",
    "从头开始",
    "clear",
    "reset",
}


def _get_planner_service() -> PlannerService:
    """为当前请求创建 Planner 服务，避免跨会话复用模型配置和内部状态。"""
    return PlannerService()


def _conversation_history(user_session: Any) -> list[ConversationTurn]:
    """把会话历史转换为受限类型；非法条目直接忽略且不进入 Planner。"""
    history = user_session.get("conversation_history", [])
    if not isinstance(history, list):
        return []
    typed_history: list[ConversationTurn] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str):
            continue
        normalized_content = content.strip()[:2000]
        if normalized_content:
            typed_history.append(ConversationTurn(role=role, content=normalized_content))
    return typed_history

def _is_explicit_clear_command(user_text: str) -> bool:
    """识别确定性的清空事件，不使用包含匹配或业务关键词猜测。"""
    normalized = user_text.strip().lower().rstrip("。.!！")
    return normalized in _CLEAR_COMMANDS


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
    logger.info("[USER_INPUT] 收到用户指令: character_count=%s", len(user_text))
    if _is_explicit_clear_command(user_text):
        await _clear_session_data(user_session)
        await reset_session_progress_sink()
        return

    progress_plan_id = f"request-{uuid.uuid4().hex[:12]}"
    progress_ledger = get_session_progress_sink()
    progress_sink = progress_ledger.begin_request()

    try:
        await progress_sink.publish(
            ProgressEvent(
                plan_id=progress_plan_id,
                step_id="planner",
                phase=ProgressPhase.PLANNING,
                status=ProgressStatus.RUNNING,
                message_code="planner_understanding",
            )
        )
        history_before_request = _conversation_history(user_session)
        append_history(user_session, "user", user_text)
        session_facts = build_session_facts(user_session)
        logger.info(
            "[SESSION_FACTS] 指令执行前状态: has_logs=%s has_log_classification=%s "
            "available_field_count=%s enum_mapping_row_count=%s "
            "enum_target_field_count=%s available_config_refs=%s",
            session_facts.has_logs,
            session_facts.has_log_classification,
            len(session_facts.available_fields),
            session_facts.enum_mapping_row_count,
            len(session_facts.enum_mapping_target_fields),
            list(session_facts.available_config_refs),
        )

        decision = await _get_planner_service().plan(
            user_text=user_text,
            conversation_history=history_before_request,
            session_facts=session_facts,
            progress_sink=progress_sink,
            progress_plan_id=progress_plan_id,
        )
        logger.info(
            "[PLANNER] 决策完成: plan_id=%s decision=%s step_count=%s operations=%s",
            decision.plan_id,
            decision.decision,
            len(decision.steps),
            [step.type for step in decision.steps],
        )
        for step in decision.steps:
            logger.info(
                "[PLANNER_STEP] 计划步骤: plan_id=%s step_id=%s operation=%s "
                "source_ref=%s config_ref=%s target_field_count=%s dependency_count=%s",
                decision.plan_id,
                step.step_id,
                step.type,
                getattr(step, "source_ref", "none"),
                getattr(step, "config_ref", "none"),
                len(getattr(step, "target_fields", ()))
                + int(bool(getattr(step, "target_field", None))),
                len(step.depends_on),
            )

        if decision.decision != "execute":
            await render_decision(decision)
            return

        # 执行器只接收 Planner 已校验的类型化步骤，原文不会继续向下游传播供猜参。
        plan_executor = PlanExecutor(create_default_adapters(team))
        execution_report = await plan_executor.execute(
            decision,
            ExecutionContext(
                session=user_session,
                session_facts=session_facts,
                progress_sink=progress_sink,
            ),
        )
        await render_execution_report(execution_report)
    finally:
        # UI 或执行器异常都必须停止心跳，避免请求结束后仍更新旧任务。
        await progress_ledger.finish_request(progress_sink)

async def _clear_session_data(user_session: Any) -> None:
    """执行确定性清空事件，并只保留统一的完成提示。"""
    if hasattr(user_session, "clear_decoded_data"):
        user_session.clear_decoded_data()
        if hasattr(user_session, "clear_mapping_results"):
            user_session.clear_mapping_results()
    else:
        for key in (
            "decoded_data",
            "decoded_fields",
            "simplified_data",
            "decoded_text",
            "original_log",
            "raw_log_lines",
            "uploaded_file_name",
            "uploaded_file_time",
            "last_mapping_data",
            "last_threat_data",
            "last_enum_extract_result",
            "mapped_sub_rules",
            "enum_preview",
            "enum_excel_path",
            "raw_base64",
        ):
            user_session.pop(key, None)
    await cl.Message(content="🗑️ **数据已清空** — 请上传新文件继续处理。").send()
