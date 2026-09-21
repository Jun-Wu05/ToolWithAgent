"""Chainlit 确定性事件适配层。

有明确领域语义的按钮一律构造类型化步骤并复用 PlanExecutor；
弹窗内部 Action 只负责把提交/取消转交表单模块续跑。
"""

import chainlit as cl
from agent.shared.logger import get_logger

logger = get_logger("action_callbacks")


@cl.action_callback("submit_rule_source_fields")
async def on_submit_rule_source_fields(action: cl.Action):
    """接收非阻塞数据源弹窗提交，并续跑触发弹窗的原始步骤。"""
    from web.rule_source_form import handle_rule_source_submission

    user_session = cl.user_session.get("user_session")
    await handle_rule_source_submission(action.payload, user_session)


@cl.action_callback("cancel_rule_source_fields")
async def on_cancel_rule_source_fields(action: cl.Action):
    """接收数据源弹窗取消或超时，并清理待执行步骤。"""
    from web.rule_source_form import handle_rule_source_cancel

    user_session = cl.user_session.get("user_session")
    await handle_rule_source_cancel(action.payload, user_session)


@cl.action_callback("start_enum_fill")
async def on_start_enum_fill(action: cl.Action):
    """把枚举填充按钮转换为显式 FillStep 并复用统一执行器。"""
    from web.deterministic_plan import execute_deterministic_plan
    from contracts.planner_models import FillStep
    from application.session_projection import build_session_facts

    user_session = cl.user_session.get("user_session")
    logger.info('[ACTION] 用户点击"开始枚举填充"按钮')
    session_facts = build_session_facts(user_session)
    if not session_facts.enum_mapping_target_fields:
        await cl.Message(content="❌ 枚举映射表丢失，请重新上传 Excel 映射表。").send()
        return
    config_ref = (
        "session.mapped_sub_rules"
        if "session.mapped_sub_rules" in session_facts.available_config_refs
        else "session.decoded_config"
    )
    step = FillStep(
        step_id="enum-fill",
        type="fill",
        fill_kind="enum",
        target_fields=session_facts.enum_mapping_target_fields,
        source_ref="session.enum_mapping_table",
        config_ref=config_ref,
    )
    await execute_deterministic_plan(
        user_session=user_session,
        team=user_session.get("team"),
        plan_id="button-enum-fill",
        steps=(step,),
    )

@cl.action_callback("export_rules")
async def on_export_rules(action: cl.Action):
    """把入口规则导出按钮转换为 ExportStep 并复用统一执行器。"""
    from web.deterministic_plan import execute_deterministic_plan
    from contracts.planner_models import ExportStep

    user_session = cl.user_session.get("user_session")
    logger.info('[ACTION] 用户点击"导出入口规则"按钮')
    step = ExportStep(
        step_id="export-entry-rules",
        type="export",
        source_ref="session.log_classification.entry_rules",
    )
    from web.rule_source_form import get_rule_source_fields, prompt_rule_source_fields

    if user_session.get("log_classification") and not get_rule_source_fields(user_session):
        await prompt_rule_source_fields(user_session, pending_step=step)
        return
    await execute_deterministic_plan(
        user_session=user_session,
        team=user_session.get("team"),
        plan_id="button-export-entry-rules",
        steps=(step,),
    )

@cl.action_callback("export_sub_rules")
async def on_export_sub_rules(action: cl.Action):
    """把子规则导出按钮转换为 ExportStep 并复用统一执行器。"""
    from web.deterministic_plan import execute_deterministic_plan
    from contracts.planner_models import ExportStep

    user_session = cl.user_session.get("user_session")
    logger.info('[ACTION] 用户点击"导出子规则"按钮')
    step = ExportStep(
        step_id="export-sub-rules",
        type="export",
        source_ref="session.log_classification.sub_rules",
    )
    from web.rule_source_form import get_rule_source_fields, prompt_rule_source_fields

    if (
        user_session.get("log_classification")
        and not user_session.get("mapped_sub_rules")
        and not get_rule_source_fields(user_session)
    ):
        await prompt_rule_source_fields(user_session, pending_step=step)
        return
    await execute_deterministic_plan(
        user_session=user_session,
        team=user_session.get("team"),
        plan_id="button-export-sub-rules",
        steps=(step,),
    )

@cl.action_callback("apply_field_mapping")
async def on_apply_field_mapping(action: cl.Action):
    """把标准字段映射按钮转换为 FieldMappingStep 并复用统一执行器。"""
    from web.deterministic_plan import execute_deterministic_plan
    from contracts.planner_models import FieldMappingStep
    from application.session_projection import build_session_facts

    user_session = cl.user_session.get("user_session")
    logger.info('[ACTION] 用户点击"标准字段映射"按钮')
    session_facts = build_session_facts(user_session)
    if not session_facts.available_fields:
        await cl.Message(content="❌ 当前没有可映射字段，请先上传并解析日志。").send()
        return
    step = FieldMappingStep(
        step_id="field-mapping",
        type="field_mapping",
        source_ref="session.fields",
    )
    from web.rule_source_form import get_rule_source_fields, prompt_rule_source_fields

    if user_session.get("log_classification") and not get_rule_source_fields(user_session):
        await prompt_rule_source_fields(user_session, pending_step=step)
        return
    await execute_deterministic_plan(
        user_session=user_session,
        team=user_session.get("team"),
        plan_id="button-field-mapping",
        steps=(step,),
    )

@cl.action_callback("export_mapped_sub_rules")
async def on_export_mapped_sub_rules(action: cl.Action):
    """把配置导出按钮转换为 ExportStep 并复用统一执行器。"""
    from web.deterministic_plan import execute_deterministic_plan
    from contracts.planner_models import ExportStep

    user_session = cl.user_session.get("user_session")
    logger.info('[ACTION] 用户点击"导出映射后子规则"按钮')
    step = ExportStep(
        step_id="export",
        type="export",
        source_ref="session.mapped_sub_rules",
    )
    await execute_deterministic_plan(
        user_session=user_session,
        team=user_session.get("team"),
        plan_id="button-export-mapped-sub-rules",
        steps=(step,),
    )


@cl.action_callback("submit_log_knowledge")
async def on_submit_log_knowledge(action: cl.Action):
    """移除当前申请动作后，以按钮专用步骤复用统一执行器。"""
    from web.deterministic_plan import execute_deterministic_plan
    from contracts.planner_models import LogKnowledgeSubmitStep

    user_session = cl.user_session.get("user_session")
    action_message_id = getattr(action, "forId", None)
    await action.remove()
    submitting_message = await cl.Message(
        content="⏳ 日志知识申请提交中，操作已暂时禁用。"
    ).send()
    logger.info('[ACTION] 用户点击"申请加入知识库"按钮')
    step = LogKnowledgeSubmitStep(
        step_id="submit-log-knowledge",
        type="log_knowledge_submit",
        submission_token=str(action.payload.get("submission_token", "")),
    )
    restore_action = False
    try:
        report = await execute_deterministic_plan(
            user_session=user_session,
            team=user_session.get("team"),
            plan_id="button-submit-log-knowledge",
            steps=(step,),
        )
        restore_action = any(
            result.artifact is not None
            and result.artifact.artifact_type == "log_knowledge_submission"
            and result.artifact.submission_status == "error"
            for result in report.results
        )
    except Exception:
        restore_action = True
        raise
    finally:
        await submitting_message.remove()
        if restore_action and action_message_id:
            await action.send(action_message_id)

