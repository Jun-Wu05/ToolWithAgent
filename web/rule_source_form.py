"""规则数据源字段的非阻塞模态表单与待执行步骤续跑。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import chainlit as cl

from agent.shared.logger import get_logger
from application.session_state import SessionState
from contracts.planner_models import ExportStep, FieldMappingStep, StepSpec
from contracts.rule_source import RuleSourceFields


RULE_SOURCE_PRODUCT_ID = "rule_source_product"
RULE_SOURCE_VENDOR_ID = "rule_source_log_vendor"
RULE_SOURCE_DATA_SOURCE_ID = "rule_source_data_source"
RULE_SOURCE_DIALOG_TIMEOUT_SECONDS = 300
logger = get_logger("rule_source_form")


def get_rule_source_fields(session: SessionState) -> RuleSourceFields | None:
    """读取并规范化当前会话的数据源字段。"""
    return RuleSourceFields.from_value(session.rule_source_fields)


def _build_dialog_props(
    *, product: str = "", log_vendor: str = "", data_source: str = ""
) -> dict[str, Any]:
    """构建模态表单初值；校验失败时保留用户已经输入的内容。"""
    return {
        RULE_SOURCE_PRODUCT_ID: product,
        RULE_SOURCE_VENDOR_ID: log_vendor,
        RULE_SOURCE_DATA_SOURCE_ID: data_source,
        "timeout_seconds": RULE_SOURCE_DIALOG_TIMEOUT_SECONDS,
    }


async def prompt_rule_source_fields(
    user_session: SessionState | None = None,
    *,
    pending_step: StepSpec | None = None,
    product: str = "",
    log_vendor: str = "",
    data_source: str = "",
) -> None:
    """发送非阻塞模态表单，避免 Action 回调被 Ask API 留在 loading 状态。"""
    session = (
        user_session
        if user_session is not None
        else cl.user_session.get("user_session")
    )
    if pending_step is not None:
        session.pending_rule_source_step = pending_step
    step_for_log = pending_step or session.pending_rule_source_step
    logger.info(
        "[RULE_SOURCE_DIALOG] 打开数据源表单: step_id=%s step_type=%s",
        getattr(step_for_log, "step_id", None),
        getattr(step_for_log, "type", None),
    )
    element = cl.CustomElement(
        name="RuleSourceDialog",
        display="inline",
        props=_build_dialog_props(
            product=product,
            log_vendor=log_vendor,
            data_source=data_source,
        ),
    )
    await cl.Message(
        content="请填写规则命名与入口规则固定字段所需的数据源信息。",
        elements=[element],
    ).send()


async def handle_rule_source_cancel(
    payload: Mapping[str, Any], user_session: SessionState
) -> None:
    """取消或前端超时时清理待执行步骤，保证下次点击可重新开始。"""
    user_session.pending_rule_source_step = None
    timed_out = payload.get("reason") == "timeout"
    logger.info(
        "[RULE_SOURCE_DIALOG] %s，已清理待执行步骤",
        "表单超时" if timed_out else "用户取消表单",
    )
    content = (
        "⌛ 数据源信息填写已超时，本次操作未执行；可重新点击按钮继续。"
        if timed_out
        else "已取消填写数据源信息，本次操作未执行。"
    )
    await cl.Message(content=content).send()


async def handle_rule_source_submission(
    payload: Mapping[str, Any], user_session: SessionState
) -> bool:
    """校验表单并保存会话字段；成功时精确续跑原始步骤。"""
    product = str(payload.get(RULE_SOURCE_PRODUCT_ID) or "").strip()
    log_vendor = str(payload.get(RULE_SOURCE_VENDOR_ID) or "").strip()
    data_source = str(payload.get(RULE_SOURCE_DATA_SOURCE_ID) or "").strip()
    try:
        fields = RuleSourceFields.create(
            product=product,
            log_vendor=log_vendor,
            data_source=data_source,
        )
    except ValueError as error:
        logger.info("[RULE_SOURCE_DIALOG] 表单校验失败，重新显示表单")
        await cl.Message(content=f"❌ {error}").send()
        await prompt_rule_source_fields(
            user_session,
            product=product,
            log_vendor=log_vendor,
            data_source=data_source,
        )
        return False

    user_session.rule_source_fields = fields
    step_to_resume = user_session.pending_rule_source_step
    user_session.pending_rule_source_step = None
    logger.info(
        "[RULE_SOURCE_DIALOG] 数据源字段已保存: resume_step_id=%s resume_step_type=%s",
        getattr(step_to_resume, "step_id", None),
        getattr(step_to_resume, "type", None),
    )

    if not isinstance(step_to_resume, (ExportStep, FieldMappingStep)):
        await cl.Message(content="✅ 数据源信息已保存，可继续生成或映射规则。").send()
        return True
    if step_to_resume.depends_on:
        await cl.Message(
            content="✅ 数据源信息已保存。原操作依赖同一计划中的前置步骤，请重新发送该请求。"
        ).send()
        return True

    from web.deterministic_plan import execute_deterministic_plan

    logger.info(
        "[RULE_SOURCE_DIALOG] 续跑待执行步骤: step_id=%s step_type=%s",
        step_to_resume.step_id,
        step_to_resume.type,
    )
    await execute_deterministic_plan(
        user_session=user_session,
        team=user_session.team,
        plan_id="resume-rule-source-fields",
        steps=(step_to_resume,),
    )
    return True


__all__ = [
    "get_rule_source_fields",
    "handle_rule_source_cancel",
    "handle_rule_source_submission",
    "prompt_rule_source_fields",
]
