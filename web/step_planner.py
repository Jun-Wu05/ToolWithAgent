"""
步骤计划推进器 — 复合意图的自动分步执行。

当 RouterAgent 通过 multi-step-plan skill 分解复合意图后，输出 [PLAN:步骤1|步骤2]
标记。本模块负责：
1. parse_plan_marker — 解析标记，返回步骤类型列表（纯函数）
2. 步骤队列管理（pop_next_step / has_pending_steps）
3. execute_step — 执行单个步骤（调用现有 handler）
4. execute_pending_steps — 自动推进队列中剩余步骤

设计原则：
- 标记解析与执行分离：parse_plan_marker 是纯函数，可单元测试
- 复用现有执行器：execute_step 不自造逻辑，调用已有 handler（fill_dispatcher / call_team 等）
- 用户原始消息全文保留：每步执行时传递，执行器自行提取所需信息
"""
from __future__ import annotations

import re
from typing import List, Optional

from agent.shared.logger import get_logger

logger = get_logger("step_planner")

# PLAN 标记正则：[PLAN:threat|fill|...]
_PLAN_RE = re.compile(r"\[PLAN:([a-z_|]+)\]")

# 合法的步骤类型（与 handler 的 intent 对应）
_VALID_STEPS = {"log_parser", "mapping", "enum", "threat", "fill"}


def parse_plan_marker(result_content: str) -> Optional[List[str]]:
    """从 LLM 响应中解析 [PLAN:...] 标记，返回步骤类型列表。

    Args:
        result_content: LLM 响应文本

    Returns:
        步骤类型列表（如 ["threat", "fill"]），无标记时返回 None。
        未知类型也会被提取（执行时由 execute_step 跳过并告警）。
    """
    match = _PLAN_RE.search(result_content)
    if not match:
        return None
    steps_str = match.group(1)
    steps = [s.strip() for s in steps_str.split("|") if s.strip()]
    return steps if steps else None


def has_pending_steps(user_session) -> bool:
    """是否还有待执行的步骤。"""
    pending = user_session.get("pending_steps") if user_session else None
    return bool(pending)


def pop_next_step(user_session) -> Optional[str]:
    """取出并移除队列中的下一个步骤。

    Returns:
        下一个步骤类型，空队列返回 None。
    """
    pending = user_session.get("pending_steps") if user_session else None
    if not pending:
        return None
    step = pending.pop(0)
    user_session["pending_steps"] = pending
    return step


async def execute_step(step_type: str, user_session, team, original_text: str) -> bool:
    """执行单个步骤，复用现有 handler。

    Args:
        step_type: 步骤类型（log_parser/mapping/enum/threat/fill）
        user_session: 会话状态
        team: Agno Team 实例
        original_text: 用户原始消息全文（执行器自行提取所需信息）

    Returns:
        True 表示步骤执行成功，False 表示失败或跳过。
    """
    if step_type not in _VALID_STEPS:
        logger.warning(f"[STEP] 未知步骤类型 '{step_type}'，跳过")
        return False

    logger.info(f"[STEP] 执行步骤: {step_type}（原文: {original_text[:60]}）")

    try:
        if step_type == "fill":
            # 填充：委托 fill_dispatcher（已有完整逻辑）
            from web.fill_dispatcher import handle_fill
            return await handle_fill(user_session, original_text)

        if step_type == "enum":
            # 枚举提取：委托 enum_handler
            from web.enum_handler import handle_enum_extract_flow
            await handle_enum_extract_flow(user_session, team, original_text)
            return True

        if step_type == "log_parser":
            # 日志解析：委托 log_parser_handler
            from web.log_parser_handler import handle_log_parser
            await handle_log_parser(user_session, original_text)
            return True

        # threat / mapping：走 call_team + response_handler（需要 LLM）
        from web.llm_client import call_team
        from web.input_builder import build_llm_input
        from web.response_handler import process_team_response
        import chainlit as cl

        full_input = build_llm_input(original_text, user_session, intent=step_type)
        loading_msg = cl.Message(content=f"⏳ **自动执行步骤：{step_type}...**")
        await loading_msg.send()

        result = await call_team(team, full_input, loading_msg, intent=step_type)
        try:
            await loading_msg.remove()
        except Exception:
            pass

        result_content = result.content if hasattr(result, "content") else str(result)
        msg = cl.Message(content="")
        await msg.send()
        handled = await process_team_response(
            result, original_text.lower(), user_session, loading_msg, msg, intent=step_type
        )
        return bool(handled)

    except Exception as e:
        logger.error(f"[STEP] 步骤 {step_type} 执行异常: {e}", exc_info=True)
        return False


async def execute_pending_steps(user_session, team, original_text: str) -> None:
    """自动推进队列中所有剩余步骤。

    在当前步骤完成后调用，依次执行 pending_steps 中的步骤。
    每步用 original_text 调用 execute_step。

    Args:
        user_session: 会话状态（含 pending_steps）
        team: Agno Team 实例
        original_text: 用户原始消息全文
    """
    while has_pending_steps(user_session):
        step = pop_next_step(user_session)
        if step is None:
            break
        success = await execute_step(step, user_session, team, original_text)
        if not success:
            logger.warning(f"[STEP] 步骤 {step} 未成功，停止后续步骤推进")
            # 清空剩余步骤，避免残留
            user_session["pending_steps"] = []
            break
        logger.info(f"[STEP] 步骤 {step} 完成，剩余 {len(user_session.get('pending_steps') or [])} 步")
