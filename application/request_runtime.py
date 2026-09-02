"""自然语言请求从 Planner 到执行报告的 Application 运行时。"""

from __future__ import annotations

from typing import Any

from agent.core.planner import PlannerService
from agent.shared.logger import get_logger
from application.adapters.composition import create_default_adapters
from application.execution import ExecutionContext
from application.execution_policy import create_plan_executor
from application.history import append_history, typed_conversation_history
from application.session_projection import build_session_facts
from contracts.planner_models import ExecutionReport, PlanDecision
from contracts.progress import ProgressEvent, ProgressPhase, ProgressSink, ProgressStatus

logger = get_logger("user_message_handlers")

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

_DECISION_LABELS = {
    "execute": "执行计划",
    "clarification": "需要澄清",
    "guidance": "使用引导",
}

_OPERATION_LABELS = {
    "log_parse": "日志类型提取",
    "field_mapping": "字段映射",
    "enum_extract": "枚举提取",
    "threat_mapping": "威胁类型映射",
    "remove_mapping": "取消映射",
    "export": "导出配置",
    "add_fields": "添加字段",
    "delete_fields": "删除字段",
    "merge_fields": "合并字段",
    "decode_fields": "base64 解码字段",
    "regex_extract": "正则提取字段",
}


def _operation_label(step: Any) -> str:
    """返回不含字段值等参数的中文业务操作名。"""
    if step.type == "fill":
        return "枚举填充" if step.fill_kind == "enum" else "威胁类型填充"
    return _OPERATION_LABELS.get(step.type, "未知操作")


def is_explicit_clear_command(user_text: str) -> bool:
    """识别可绕过 Planner 的完整清空命令。"""
    normalized = user_text.strip().lower().rstrip("。.!！")
    return normalized in _CLEAR_COMMANDS


def clear_session_data(session: Any) -> None:
    """清除业务会话状态，不承担界面提示或进度账本重置。"""
    if hasattr(session, "clear_decoded_data"):
        session.clear_decoded_data()
        if hasattr(session, "clear_mapping_results"):
            session.clear_mapping_results()
        return
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
        "latest_threat_artifact",
        "latest_enum_artifact",
        "rule_source_fields",
        "pending_rule_source_step",
        "mapped_sub_rules",
        "enum_preview",
        "enum_excel_path",
        "raw_base64",
    ):
        session.pop(key, None)


async def run_user_request(
    *,
    session: Any,
    team: Any,
    user_text: str,
    progress_sink: ProgressSink,
    progress_plan_id: str,
    planner: PlannerService | Any | None = None,
) -> PlanDecision | ExecutionReport:
    """规划并按决策执行一次自然语言请求，不包含界面渲染。"""
    logger.info(
        "[USER_INPUT] 收到用户指令: user_text=%s character_count=%s",
        user_text,
        len(user_text),
    )
    await progress_sink.publish(
        ProgressEvent(
            plan_id=progress_plan_id,
            step_id="planner",
            phase=ProgressPhase.PLANNING,
            status=ProgressStatus.RUNNING,
            message_code="planner_understanding",
        )
    )
    history_before_request = typed_conversation_history(session)
    append_history(session, "user", user_text)
    session_facts = build_session_facts(session)
    logger.info(
        "[SESSION_FACTS] 指令执行前状态: has_logs=%s has_log_classification=%s "
        "available_field_count=%s mappable_field_count=%s enum_mapping_row_count=%s "
        "enum_target_field_count=%s available_config_refs=%s referenceable_artifacts=%s",
        session_facts.has_logs,
        session_facts.has_log_classification,
        len(session_facts.available_fields),
        len(session_facts.mappable_fields),
        session_facts.enum_mapping_row_count,
        len(session_facts.enum_mapping_target_fields),
        list(session_facts.available_config_refs),
        [item.source_ref for item in session_facts.referenceable_artifacts],
    )
    planner_runtime = planner or PlannerService()
    decision = await planner_runtime.plan(
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
    logger.info(
        "[PLANNER_INTENT] 中文意图摘要: plan_id=%s decision_cn=%s operations_cn=%s",
        decision.plan_id,
        _DECISION_LABELS[decision.decision],
        [_operation_label(step) for step in decision.steps],
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
        return decision
    return await create_plan_executor(create_default_adapters(team)).execute(
        decision,
        ExecutionContext(
            session=session,
            session_facts=session_facts,
            progress_sink=progress_sink,
        ),
    )


async def run_deterministic_plan(
    *,
    session: Any,
    team: Any,
    plan: PlanDecision,
    progress_sink: ProgressSink,
) -> ExecutionReport:
    """执行入口已提供全部参数的类型化确定性计划。"""
    session_facts = build_session_facts(session)
    return await create_plan_executor(create_default_adapters(team)).execute(
        plan,
        ExecutionContext(
            session=session,
            session_facts=session_facts,
            progress_sink=progress_sink,
        ),
    )
