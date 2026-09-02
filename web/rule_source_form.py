"""规则数据源字段的 Chainlit 共用表单与待执行步骤续跑。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import chainlit as cl
from chainlit.input_widget import TextInput

from contracts.planner_models import ExportStep, FieldMappingStep, StepSpec
from contracts.rule_source import RuleSourceFields


RULE_SOURCE_PRODUCT_ID = "rule_source_product"
RULE_SOURCE_VENDOR_ID = "rule_source_log_vendor"
RULE_SOURCE_DATA_SOURCE_ID = "rule_source_data_source"
_RULE_SOURCE_IDS = {
    RULE_SOURCE_PRODUCT_ID,
    RULE_SOURCE_VENDOR_ID,
    RULE_SOURCE_DATA_SOURCE_ID,
}


def _session_get(session: Any, key: str, default: Any = None) -> Any:
    if isinstance(session, Mapping):
        return session.get(key, default)
    return getattr(session, key, default)


def _session_set(session: Any, key: str, value: Any) -> None:
    if isinstance(session, dict):
        session[key] = value
    else:
        setattr(session, key, value)


def get_rule_source_fields(session: Any) -> RuleSourceFields | None:
    """读取并规范化当前会话的数据源字段。"""
    return RuleSourceFields.from_value(_session_get(session, "rule_source_fields"))


def build_rule_source_widgets(
    *, product: str = "", log_vendor: str = "", data_source: str = ""
) -> list[TextInput]:
    """构建与模型设置 ID 隔离的三字段表单。"""
    return [
        TextInput(
            id=RULE_SOURCE_PRODUCT_ID,
            label="数据源产品（必填）",
            placeholder="例如：防火墙产品",
            initial=product,
        ),
        TextInput(
            id=RULE_SOURCE_VENDOR_ID,
            label="数据源厂商（必填）",
            placeholder="例如：XX厂商",
            initial=log_vendor,
        ),
        TextInput(
            id=RULE_SOURCE_DATA_SOURCE_ID,
            label="数据源（可选）",
            placeholder="留空则自动生成：数据源产品(数据源厂商)",
            initial=data_source,
        ),
    ]


async def prompt_rule_source_fields(
    user_session: Any | None = None,
    *,
    pending_step: StepSpec | None = None,
    product: str = "",
    log_vendor: str = "",
    data_source: str = "",
) -> None:
    """显示共用表单，并可记录提交后要继续执行的原始步骤。"""
    session = (
        user_session
        if user_session is not None
        else cl.user_session.get("user_session")
    )
    if pending_step is not None:
        _session_set(session, "pending_rule_source_step", pending_step)
    await cl.ChatSettings(
        build_rule_source_widgets(
            product=product,
            log_vendor=log_vendor,
            data_source=data_source,
        )
    ).send()


def is_rule_source_settings(settings: Mapping[str, Any]) -> bool:
    """判断全局设置回调收到的是否为数据源专用表单。"""
    return bool(_RULE_SOURCE_IDS.intersection(settings))


async def handle_rule_source_settings(
    settings: Mapping[str, Any], user_session: Any
) -> bool:
    """处理、保存数据源表单；成功时续跑无依赖的待执行步骤。"""
    if not is_rule_source_settings(settings):
        return False

    product = str(settings.get(RULE_SOURCE_PRODUCT_ID) or "")
    log_vendor = str(settings.get(RULE_SOURCE_VENDOR_ID) or "")
    data_source = str(settings.get(RULE_SOURCE_DATA_SOURCE_ID) or "")
    try:
        fields = RuleSourceFields.create(
            product=product,
            log_vendor=log_vendor,
            data_source=data_source,
        )
    except ValueError as error:
        await cl.Message(content=f"❌ {error}").send()
        await prompt_rule_source_fields(
            user_session,
            product=product.strip(),
            log_vendor=log_vendor.strip(),
            data_source=data_source.strip(),
        )
        return True

    _session_set(user_session, "rule_source_fields", fields)
    pending_step = _session_get(user_session, "pending_rule_source_step")
    _session_set(user_session, "pending_rule_source_step", None)

    if not isinstance(pending_step, (ExportStep, FieldMappingStep)):
        await cl.Message(content="✅ 数据源信息已保存，可继续生成或映射规则。").send()
        return True
    if pending_step.depends_on:
        await cl.Message(
            content="✅ 数据源信息已保存。原操作依赖同一计划中的前置步骤，请重新发送该请求。"
        ).send()
        return True

    from web.deterministic_plan import execute_deterministic_plan

    await execute_deterministic_plan(
        user_session=user_session,
        team=_session_get(user_session, "team"),
        plan_id="resume-rule-source-fields",
        steps=(pending_step,),
    )
    return True


__all__ = [
    "build_rule_source_widgets",
    "get_rule_source_fields",
    "handle_rule_source_settings",
    "is_rule_source_settings",
    "prompt_rule_source_fields",
]
