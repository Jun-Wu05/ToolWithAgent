"""自然语言请求从 Planner 到执行报告的 Application 运行时。"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any, Awaitable, Callable

from agent.core.model_config import model_runtime_scope
from agent.core.planner import PlannerService
from agent.shared.logger import get_logger
from application.adapters.composition import create_default_adapters
from application.execution import ExecutionContext
from application.execution_continuation import ExecutionContinuation
from application.execution_policy import create_plan_executor
from application.history import append_history, typed_conversation_history
from application.model_runtime import resolve_session_config
from application.progress import NullProgressSink
from application.session_projection import build_session_facts, summarize_report
from application.session_state import SessionState
from application.threat_chain import (
    build_threat_source_plan,
    compile_explicit_threat_plan,
    commit_threat_chain_session,
    is_threat_type_replacement_plan,
    rank_threat_source_candidates,
    run_threat_chain_after_mapping,
    set_threat_source_override,
    stage_threat_chain_session,
)
from contracts.planner_models import (
    ExecutionReport,
    DeterministicPlan,
    PendingPlan,
    PlanDecision,
    StepStatus,
    ThreatMappingArtifact,
)
from contracts.progress import ProgressEvent, ProgressPhase, ProgressSink, ProgressStatus
from contracts.session_facts import SessionFacts

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


async def _execute_plan_with_threat_transaction(
    *,
    session: SessionState,
    team: Any,
    plan: PlanDecision | DeterministicPlan,
    progress_sink: ProgressSink,
    session_facts: SessionFacts | None = None,
    adapters: Mapping[str, Any] | None = None,
    continuation: ExecutionContinuation | None = None,
    checkpoint: dict | None = None,
) -> ExecutionReport:
    """显式威胁全链在配置副本上执行，整计划成功后才提交。"""
    transactional = is_threat_type_replacement_plan(plan.steps)
    execution_session = (
        stage_threat_chain_session(session) if transactional else session
    )
    execution_facts = (
        build_session_facts(execution_session)
        if transactional or session_facts is None
        else session_facts
    )
    report = await create_plan_executor(adapters if adapters is not None else create_default_adapters(team)).execute(
        plan,
        ExecutionContext(
            session=execution_session,
            session_facts=execution_facts,
            progress_sink=progress_sink,
            checkpoint=checkpoint,
        ),
        **({"continuation": continuation} if continuation is not None else {}),
    )
    if checkpoint is not None:
        # 持久化入口使用实际执行副本，不能把失败后未提交的外层会话当成 staging。
        checkpoint["execution_session"] = execution_session
        checkpoint["frozen_plan"] = DeterministicPlan(plan_id=plan.plan_id, steps=plan.steps).model_dump(mode="json")
    if transactional and report.status == StepStatus.SUCCESS:
        commit_threat_chain_session(execution_session, session)
    return report


_RETRYABLE_THREAT_SOURCE_ERRORS = {
    "enum_extract_empty",
    "enum_target_field_not_found",
    "threat_mapping_empty",
}


def _has_meaningful_threat_mapping(report: ExecutionReport) -> bool:
    """自动试选至少得到一个非“其他”映射才允许提交。"""
    return any(
        isinstance(result.artifact, ThreatMappingArtifact)
        and any(
            row.mapped_value.strip() and row.mapped_value.strip() != "其他"
            for row in result.artifact.mappings
        )
        for result in report.results
    )


async def _run_auto_threat_source_selection(
    *, session: SessionState, team: Any, session_facts: SessionFacts
) -> PlanDecision | ExecutionReport:
    """在隔离会话中最多试三个真实来源，首个有效全链成功后一次提交。"""
    candidates = rank_threat_source_candidates(session_facts.threat_source_fields)
    if not candidates:
        return PlanDecision(
            decision="clarification",
            plan_id="auto-threat-source",
            reason_code="threat_source_required",
            question="当前威胁子规则没有可试选的共同来源字段。",
        )

    for position, source_field in enumerate(candidates, start=1):
        staged_session = stage_threat_chain_session(session)
        plan = build_threat_source_plan(
            staged_session,
            source_field,
            plan_id=f"plan-threat-source-auto-{position}",
        )
        if plan is None:
            break
        report = await _execute_plan_with_threat_transaction(
            session=staged_session,
            team=team,
            plan=plan,
            progress_sink=NullProgressSink(),
        )
        _record_execution_summary(session, report)
        if report.status == StepStatus.SUCCESS and _has_meaningful_threat_mapping(report):
            commit_threat_chain_session(staged_session, session)
            set_threat_source_override(session, source_field)
            logger.info(
                "[THREAT_CHAIN] 自动来源试选成功: source=%s attempt=%s",
                source_field,
                position,
            )
            return report
        failed = next(
            (result for result in report.results if result.status != StepStatus.SUCCESS),
            None,
        )
        if failed is not None and failed.error_code not in _RETRYABLE_THREAT_SOURCE_ERRORS:
            return report
        logger.info(
            "[THREAT_CHAIN] 自动来源试选未命中: source=%s attempt=%s error=%s",
            source_field,
            position,
            failed.error_code if failed is not None else "all_degraded",
        )

    return PlanDecision(
        decision="clarification",
        plan_id="auto-threat-source",
        reason_code="threat_source_required",
        question="自动尝试未找到可可靠映射的威胁类型来源，请明确选择一个字段。",
        choices=candidates,
    )


_DECISION_LABELS = {
    "execute": "执行计划",
    "proposal": "待确认方案",
    "confirm": "确认方案",
    "cancel": "取消方案",
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

_STEP_STATUS_LABELS = {
    StepStatus.SUCCESS: "成功",
    StepStatus.NEEDS_INPUT: "待补充",
    StepStatus.FAILED: "失败",
}


def _operation_label(step: Any) -> str:
    """返回不含字段值等参数的中文业务操作名。"""
    if step.type == "fill":
        return "枚举填充" if step.fill_kind == "enum" else "威胁类型填充"
    return _OPERATION_LABELS.get(step.type, "未知操作")


def _assistant_history_content(result: PlanDecision | ExecutionReport) -> str:
    """生成供下一轮 Planner 续接的紧凑助手语义，不保存产物内容。"""
    if isinstance(result, PlanDecision):
        if result.decision in {"clarification", "proposal"}:
            choices = f" 可选：{'；'.join(result.choices)}" if result.choices else ""
            return f"{result.question}{choices}"
        if result.answer:
            return result.answer
        return "已提供使用引导。"

    outcomes = []
    for item in result.results:
        fallback = "填充" if item.operation_type == "fill" else item.operation_type
        operation = _OPERATION_LABELS.get(item.operation_type, fallback)
        status = _STEP_STATUS_LABELS[item.status]
        outcomes.append(f"{operation}（{status}）")
    return f"已执行：{'；'.join(outcomes)}。"


def _record_execution_summary(session: SessionState, report: ExecutionReport) -> None:
    """把一份已完成计划滚动写入当前/上一份安全摘要槽位。"""
    session.previous_execution = session.current_execution
    session.current_execution = summarize_report(report)


def _read_pending_plan(session: SessionState) -> PendingPlan | None:
    """读取类型化待确认计划；损坏状态按不存在处理。"""
    value = session.pending_plan
    if value is None:
        return None
    try:
        return value if isinstance(value, PendingPlan) else PendingPlan.model_validate(value)
    except (TypeError, ValueError):
        session.pending_plan = None
        return None


def _session_facts_digest(session_facts: SessionFacts) -> str:
    """生成稳定事实摘要，确认时拒绝执行基于旧状态的计划。"""
    payload = session_facts.model_dump_json().encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _pending_plan_error(plan_id: str, reason_code: str, question: str) -> PlanDecision:
    """构造不泄露计划内容的通用待确认状态错误。"""
    return PlanDecision(
        decision="clarification",
        plan_id=plan_id,
        reason_code=reason_code,
        question=question,
    )


def is_explicit_clear_command(user_text: str) -> bool:
    """识别可绕过 Planner 的完整清空命令。"""
    normalized = user_text.strip().lower().rstrip("。.!！")
    return normalized in _CLEAR_COMMANDS


def clear_session_data(session: SessionState) -> None:
    """清除业务会话状态，不承担界面提示或进度账本重置。"""
    session.clear_decoded_data()
    session.clear_mapping_results()



async def run_user_request(
    *,
    session: SessionState,
    team: Any,
    user_text: str,
    progress_sink: ProgressSink,
    progress_plan_id: str,
    planner: PlannerService | Any | None = None,
    adapters: Mapping[str, Any] | None = None,
    on_plan: Callable[[PlanDecision], None] | None = None,
    checkpoint: dict | None = None,
) -> PlanDecision | ExecutionReport:
    """规划并按决策执行一次自然语言请求，不包含界面渲染。

    整条链（Planner、执行器、威胁链续跑、直连 LLM）绑定请求启动时的
    会话配置快照；执行期间的同会话设置修改从下一次请求生效（#192）。
    """
    with model_runtime_scope(resolve_session_config(session)):
        return await _run_user_request_scoped(
            session=session,
            team=team,
            user_text=user_text,
            progress_sink=progress_sink,
            progress_plan_id=progress_plan_id,
            planner=planner,
            adapters=adapters,
            on_plan=on_plan,
            checkpoint=checkpoint,
        )


async def _run_user_request_scoped(
    *,
    session: SessionState,
    team: Any,
    user_text: str,
    progress_sink: ProgressSink,
    progress_plan_id: str,
    planner: PlannerService | Any | None = None,
    adapters: Mapping[str, Any] | None = None,
    on_plan: Callable[[PlanDecision], None] | None = None,
    checkpoint: dict | None = None,
) -> PlanDecision | ExecutionReport:
    """会话作用域内的实际规划与执行链（入口见 run_user_request）。"""
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
    pending_plan = _read_pending_plan(session)
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
        pending_plan=pending_plan,
        progress_sink=progress_sink,
        progress_plan_id=progress_plan_id,
    )
    decision = compile_explicit_threat_plan(decision, session)
    if on_plan is not None:
        on_plan(decision)
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
    if decision.reason_code == "threat_source_auto_requested":
        session.pending_plan = None
        auto_result = await _run_auto_threat_source_selection(
            session=session,
            team=team,
            session_facts=session_facts,
        )
        append_history(session, "assistant", _assistant_history_content(auto_result))
        return auto_result
    if decision.decision == "proposal":
        session.pending_plan = PendingPlan(
            plan_id=decision.plan_id,
            steps=decision.steps,
            session_facts_digest=_session_facts_digest(session_facts),
        )
        append_history(session, "assistant", _assistant_history_content(decision))
        return decision
    if decision.decision in {"confirm", "cancel"}:
        if pending_plan is None or decision.pending_plan_id != pending_plan.plan_id:
            result = _pending_plan_error(
                decision.plan_id,
                "pending_plan_not_found",
                "没有匹配的待确认方案，请重新提出操作要求。",
            )
            append_history(session, "assistant", _assistant_history_content(result))
            return result
        if decision.decision == "cancel":
            session.pending_plan = None
            result = PlanDecision(
                decision="guidance",
                plan_id=decision.plan_id,
                guidance_code="pending_plan_cancelled",
                answer="已取消待执行方案。",
            )
            append_history(session, "assistant", _assistant_history_content(result))
            return result
        if pending_plan.session_facts_digest != _session_facts_digest(session_facts):
            session.pending_plan = None
            result = _pending_plan_error(
                decision.plan_id,
                "pending_plan_stale",
                "会话数据已变化，原方案已失效，请重新提出操作要求。",
            )
            append_history(session, "assistant", _assistant_history_content(result))
            return result
        session.pending_plan = None
        decision = PlanDecision(
            decision="execute",
            plan_id=pending_plan.plan_id,
            steps=pending_plan.steps,
        )
    elif decision.decision != "execute":
        session.pending_plan = None
        append_history(session, "assistant", _assistant_history_content(decision))
        return decision
    else:
        session.pending_plan = None
    report = await _execute_plan_with_threat_transaction(
        session=session,
        team=team,
        plan=decision,
        progress_sink=progress_sink,
        session_facts=session_facts,
        adapters=adapters,
        checkpoint=checkpoint,
    )
    # 执行后确定性续跑（#173）：字段映射判出威胁子规则时自动补全威胁类型链路
    final_report = await run_threat_chain_after_mapping(
        report=report,
        plan_steps=decision.steps,
        session=session,
        team=team,
        progress_sink=progress_sink,
        adapters=adapters,
    )
    _record_execution_summary(session, final_report)
    append_history(session, "assistant", _assistant_history_content(final_report))
    return final_report


async def run_deterministic_plan(
    *,
    session: SessionState,
    team: Any,
    plan: DeterministicPlan,
    progress_sink: ProgressSink,
    on_primary_report: Callable[[ExecutionReport], Awaitable[None]] | None = None,
    adapters: Mapping[str, Any] | None = None,
    continuation: ExecutionContinuation | None = None,
    checkpoint: dict | None = None,
) -> ExecutionReport:
    """执行入口已提供全部参数的类型化确定性计划（同样绑定会话配置快照）。"""
    with model_runtime_scope(resolve_session_config(session)):
        return await _run_deterministic_plan_scoped(
            session=session,
            team=team,
            plan=plan,
            progress_sink=progress_sink,
            on_primary_report=on_primary_report,
            adapters=adapters,
            continuation=continuation,
            checkpoint=checkpoint,
        )


async def _run_deterministic_plan_scoped(
    *,
    session: SessionState,
    team: Any,
    plan: DeterministicPlan,
    progress_sink: ProgressSink,
    on_primary_report: Callable[[ExecutionReport], Awaitable[None]] | None,
    adapters: Mapping[str, Any] | None,
    continuation: ExecutionContinuation | None,
    checkpoint: dict | None,
) -> ExecutionReport:
    """会话作用域内的确定性计划执行链（入口见 run_deterministic_plan）。"""
    report = await _execute_plan_with_threat_transaction(
        session=session,
        team=team,
        plan=plan,
        progress_sink=progress_sink,
        adapters=adapters,
        continuation=continuation,
        checkpoint=checkpoint,
    )
    if on_primary_report is not None:
        await on_primary_report(report)
    # 执行后确定性续跑（#173）：按钮/确定性入口的字段映射同样触发威胁链路
    final_report = await run_threat_chain_after_mapping(
        report=report,
        plan_steps=plan.steps,
        session=session,
        team=team,
        progress_sink=progress_sink,
        adapters=adapters,
    )
    _record_execution_summary(session, final_report)
    return final_report
