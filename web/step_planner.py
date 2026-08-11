"""
步骤计划推进器 — 复合意图的自动分步执行。

当 RouterAgent 通过 multi-step-plan skill 分解复合意图后，输出 [PLAN:...] 标记。
本模块负责：
1. parse_plan_marker — 解析标记，返回结构化步骤列表（纯函数）
2. clean_plan_marker — 从展示文本中清理 PLAN 标记（纯函数）
3. 步骤队列管理（pop_next_step / has_pending_steps）
4. execute_step — 执行单个步骤（调用现有 handler）
5. execute_pending_steps — 自动推进队列中剩余步骤

标记格式（ADR-0004）：
  新格式（JSON，携带参数）：
    [PLAN:{"steps":[{"type":"enum","params":{"field":"漏洞名称"}},...]}]
  旧格式（无参数，向后兼容）：
    [PLAN:enum|threat|fill]

设计原则：
- 标记解析与执行分离：parse_plan_marker 是纯函数，可单元测试
- 复用现有执行器：execute_step 不自造逻辑，调用已有 handler（fill_dispatcher / call_team 等）
- 用户原始消息全文保留：每步执行时传递，执行器自行提取所需信息
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from agent.shared.logger import get_logger

logger = get_logger("step_planner")

# JSON 格式标记：[PLAN:{...}]（ADR-0004 新格式，携带 params + data_deps）
# 贪婪匹配到 }]]，正确处理 JSON 内部的嵌套花括号
_PLAN_JSON_RE = re.compile(r"\[PLAN:(\{.*\})\]")

# 旧式无参数标记：[PLAN:enum|threat|fill]（向后兼容）
_PLAN_LEGACY_RE = re.compile(r"\[PLAN:([a-z_|]+)\]")

# 合法的步骤类型（与 handler 的 intent 对应）
_VALID_STEPS = {"log_parser", "mapping", "enum", "threat", "fill"}


def parse_plan_marker(result_content: str) -> Optional[List[Dict[str, Any]]]:
    """从 LLM 响应中解析 [PLAN:...] 标记，返回结构化步骤列表。

    优先尝试 JSON 格式（ADR-0004 新格式），失败回退旧式无参数格式。

    Args:
        result_content: LLM 响应文本

    Returns:
        步骤字典列表，每步至少含 ``type`` 键，可选 ``params`` / ``data_deps``。
        如 ``[{"type":"enum","params":{"field":"漏洞名称"}}, {"type":"threat"}]``。
        无标记或 JSON 解析失败时返回 None。空 steps 列表也返回 None。
    """
    # 优先尝试 JSON 格式
    json_match = _PLAN_JSON_RE.search(result_content)
    if json_match:
        try:
            plan = json.loads(json_match.group(1))
            steps = plan.get("steps", [])
            if not steps:
                return None
            # 只保留有 type 的步骤（过滤无效条目）
            valid = [s for s in steps if isinstance(s, dict) and s.get("type")]
            return valid if valid else None
        except (json.JSONDecodeError, AttributeError) as e:
            logger.debug(f"[PLAN] JSON 标记解析失败，尝试旧式格式: {e}")
            # 不 return，继续尝试旧式

    # 回退旧式无参数格式
    legacy_match = _PLAN_LEGACY_RE.search(result_content)
    if legacy_match:
        steps_str = legacy_match.group(1)
        type_list = [s.strip() for s in steps_str.split("|") if s.strip()]
        if not type_list:
            return None
        # 转为统一的结构化格式（只有 type，无 params/data_deps）
        return [{"type": t} for t in type_list]

    return None


def clean_plan_marker(result_content: str) -> str:
    """从展示文本中移除 PLAN 标记（新旧格式均处理）。

    供 user_message_handlers 在向用户展示 RouterAgent 的分解说明时调用，
    避免 [PLAN:...] 原始标记泄漏到用户可见文本。

    Args:
        result_content: 含 PLAN 标记的 LLM 响应文本

    Returns:
        清理后的文本（标记被移除，首尾空白被 strip）。无标记时原样返回。
    """
    # 先清理 JSON 格式标记，再清理旧式标记
    cleaned = _PLAN_JSON_RE.sub("", result_content)
    cleaned = _PLAN_LEGACY_RE.sub("", cleaned)
    return cleaned.strip()


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


async def execute_step(
    step_type: str,
    user_session,
    team,
    original_text: str,
    step_params: dict | None = None,
) -> bool:
    """执行单个步骤，复用现有 handler。

    Args:
        step_type: 步骤类型（log_parser/mapping/enum/threat/fill）
        user_session: 会话状态
        team: Agno Team 实例
        original_text: 用户原始消息全文（日志类型过滤等仍需使用）
        step_params: 步骤参数（ADR-0004，来自 PLAN 计划的 params）。
            如 ``{"field": "漏洞名称", "source": "threat"}``。
            None 时（旧式无参数标记）走 handler 的自然语言适配路径。

    Returns:
        True 表示步骤执行成功，False 表示失败或跳过。
    """
    if step_type not in _VALID_STEPS:
        logger.warning(f"[STEP] 未知步骤类型 '{step_type}'，跳过")
        return False

    logger.info(f"[STEP] 执行步骤: {step_type}（原文: {original_text[:60]}，参数: {step_params}）")

    try:
        if step_type == "fill":
            # 填充：有显式参数走参数化核心接口，否则走自然语言适配器
            from web.fill_dispatcher import handle_fill_from_params, handle_fill_from_text
            if step_params and (step_params.get("field") or step_params.get("source")):
                target_field = step_params.get("field")
                fill_type = step_params.get("source", "threat")
                await handle_fill_from_params(user_session, target_field, fill_type)
            else:
                await handle_fill_from_text(user_session, original_text)
            # 执行后验证：fill 后 mapped_sub_rules 的 mappings 必须非空
            return verify_step_result("fill", user_session)

        if step_type == "enum":
            # 枚举提取：有显式 field_name 传入，否则走 LLM 推断
            from web.enum_handler import handle_enum_extract_flow
            field_name = step_params.get("field") if step_params else None
            await handle_enum_extract_flow(user_session, team, original_text, field_name=field_name)
            # 执行后验证：enum 必须提取到至少 1 个值
            return verify_step_result("enum", user_session)

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
        # threat 步骤额外验证：last_threat_data 必须非空
        if step_type == "threat" and handled:
            return verify_step_result("threat", user_session)
        return bool(handled)

    except Exception as e:
        logger.error(f"[STEP] 步骤 {step_type} 执行异常: {e}", exc_info=True)
        return False


async def execute_pending_steps(user_session, team, original_text: str) -> None:
    """自动推进队列中所有剩余步骤。

    执行流程（ADR-0004 三层校验）：
    1. 结构校验（整批一次）：validate_plan_structure 检查 JSON 计划格式
    2. 逐步执行：
       a. 语义校验（逐步）：validate_plan_semantics 检查当前步 params 对照 session
       b. execute_step 执行
       c. 执行后验证：verify_step_result 检查结果非空
    任一步失败即停止并清空队列。

    双轨兼容（ADR-0004 迁移期）：pending_steps 的元素可能是：
    - 结构化 dict（新 JSON 格式）：取 ``step["type"]`` 传给 execute_step
    - 纯 type 字符串（旧式/直接构造）：直接传给 execute_step

    Args:
        user_session: 会话状态（含 pending_steps）
        team: Agno Team 实例
        original_text: 用户原始消息全文
    """
    from web.plan_validator import (
        validate_plan_structure,
        validate_plan_semantics,
    )

    # ① 结构校验（整批一次，仅对 dict 格式的步骤生效）
    pending = user_session.get("pending_steps") if user_session else None
    if pending and all(isinstance(s, dict) for s in pending):
        struct_result = validate_plan_structure(pending)
        if not struct_result.valid:
            logger.warning(f"[STEP] 结构校验失败，停止执行: {struct_result.errors}")
            import chainlit as cl
            await cl.Message(
                content=f"⚠️ 步骤计划格式有误，无法自动执行：\n"
                + "\n".join(f"- {e}" for e in struct_result.errors)
            ).send()
            user_session["pending_steps"] = []
            return

    while has_pending_steps(user_session):
        step = pop_next_step(user_session)
        if step is None:
            break
        # 双轨：dict 取 type，字符串直接用（#18 会改为传递完整 params）
        step_type = step["type"] if isinstance(step, dict) else step

        # ② 语义校验（逐步，仅对 dict 格式生效）
        if isinstance(step, dict):
            sem_result = validate_plan_semantics([step], user_session)
            if not sem_result.valid:
                logger.warning(f"[STEP] 步骤 {step_type} 语义校验失败: {sem_result.errors}")
                import chainlit as cl
                await cl.Message(
                    content=f"⚠️ 步骤「{step_type}」参数校验未通过，请补充信息：\n"
                    + "\n".join(f"- {e}" for e in sem_result.errors)
                ).send()
                # 语义校验失败：追问而非静默跳过，停止后续步骤
                user_session["pending_steps"] = []
                break

        success = await execute_step(
            step_type, user_session, team, original_text,
            step_params=step.get("params") if isinstance(step, dict) else None,
        )
        if not success:
            logger.warning(f"[STEP] 步骤 {step_type} 未成功（执行失败或结果为空），停止后续步骤推进")
            # 清空剩余步骤，避免残留
            user_session["pending_steps"] = []
            break
        logger.info(f"[STEP] 步骤 {step_type} 完成，剩余 {len(user_session.get('pending_steps') or [])} 步")
