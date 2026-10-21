"""威胁类型链路编排（#173）：字段映射成功后的执行后确定性续跑。

新计划产生源（ADR-0010）：Planner 预生成不可行——事件标注发生在执行中，
计划无法在规划期知道威胁判定；适配器内部串破坏单一职责。因此在
application 请求运行时层后置检查标注结果，构造确定性四步计划
（enum_extract → threat_mapping → [delete] → add_fields → fill）经统一
执行器续跑，执行账本完整。

失败语义：链路失败不阻塞、不回滚字段映射本身的成功报告——仅追加成功的
链路步骤行与一条 🔗/⚠️ 汇总行（失败原因写入汇总文本，不降级整体状态）。
"""

from __future__ import annotations

import copy
import re
import time
from contextlib import contextmanager
from typing import Any, Iterator

from agent.core.field_retriever import batch_retrieve_candidates_table
from agent.core.tracing import TraceContext
from agent.shared.event_classify import THREAT_EVENT_NAMES
from agent.shared.logger import get_logger
from application.adapters.composition import create_default_adapters
from application.execution import ExecutionContext
from application.execution_policy import create_plan_executor
from application.progress import NullProgressSink
from application.recovery import RecoveryBudget
from application.session_projection import build_session_facts
from application.session_state import SessionState
from application.threat_chain_policy import (
    ChainTrigger,
    SourceFieldDecision,
    ThreatChainPlan,
    build_threat_chain_steps,
    collect_threat_field_pools,
    degraded_mapping_ratio,
    determine_source_field,
    evaluate_chain_trigger,
    inspect_threat_field_state,
    is_safe_rederive_plan,
    should_rederive,
)
from application.threat_report import refresh_report_event_annotations
from contracts.planner_models import (
    AddFieldsStep,
    DeleteFieldsStep,
    EnumExtractStep,
    ExecutionReport,
    FillStep,
    PlanDecision,
    StepResult,
    StepStatus,
    StepSpec,
    ThreatMappingArtifact,
    ThreatMappingStep,
    THREAT_TYPE_FIELD,
)
from contracts.progress import ProgressSink

logger = get_logger("threat_chain")
recovery_logger = get_logger("recovery")

CHAIN_PLAN_ID = "threat-chain-auto"
"""链路续跑计划 ID（进度与日志可按此归组）。"""

SUMMARY_STEP_ID = "threat-chain"
"""链路汇总行的 step_id（渲染为报告末尾的 🔗/⚠️ 段落）。"""

CHAIN_CONFIG_REF = "session.mapped_sub_rules"
"""自动链路的目标配置：事件标注所在处（mapped_sub_rules）。"""

def stage_threat_chain_session(session: SessionState) -> SessionState:
    """为威胁链构造隔离会话，其他输入只读共享、目标配置深拷贝。"""
    staged = copy.copy(session)
    staged.mapped_sub_rules = copy.deepcopy(session.mapped_sub_rules)
    return staged


def commit_threat_chain_session(staged: SessionState, session: SessionState) -> None:
    """整条链成功后一次性提交配置与可引用产物（显式五键，纳入写入守卫视野）。"""
    session.mapped_sub_rules = staged.mapped_sub_rules
    session.last_enum_extract_result = staged.last_enum_extract_result
    session.latest_enum_artifact = staged.latest_enum_artifact
    session.last_threat_data = staged.last_threat_data
    session.latest_threat_artifact = staged.latest_threat_artifact


def set_threat_source_override(session: SessionState, source_field: str) -> None:
    """记录已成功验证的威胁来源，供本会话后续自动链复用。"""
    session.threat_source_field_override = source_field


def is_threat_type_replacement_plan(plan_steps: tuple[StepSpec, ...]) -> bool:
    """识别同时包含生成字段与威胁填充的显式威胁全链。"""
    has_generated_field = any(
        isinstance(step, AddFieldsStep) and step.field_name == THREAT_TYPE_FIELD
        for step in plan_steps
    )
    has_threat_fill = any(
        isinstance(step, FillStep)
        and step.fill_kind == "threat"
        and step.target_fields == (THREAT_TYPE_FIELD,)
        for step in plan_steps
    )
    return has_generated_field and has_threat_fill


def compile_explicit_threat_plan(plan: PlanDecision, session: SessionState) -> PlanDecision:
    """把 Planner 的威胁来源语义骨架编译为匹配当前配置的确定性链路。"""
    if plan.decision not in {"execute", "proposal"}:
        return plan
    allowed = (
        EnumExtractStep,
        ThreatMappingStep,
        DeleteFieldsStep,
        AddFieldsStep,
        FillStep,
    )
    if not plan.steps or any(not isinstance(step, allowed) for step in plan.steps):
        return plan

    enum_steps = [step for step in plan.steps if isinstance(step, EnumExtractStep)]
    mapping_steps = [step for step in plan.steps if isinstance(step, ThreatMappingStep)]
    add_steps = [
        step
        for step in plan.steps
        if isinstance(step, AddFieldsStep)
        and step.field_name == THREAT_TYPE_FIELD
        and step.value_type == "reference"
        and step.rule_group == "threat"
    ]
    fill_steps = [
        step
        for step in plan.steps
        if isinstance(step, FillStep)
        and step.fill_kind == "threat"
        and step.target_fields == (THREAT_TYPE_FIELD,)
    ]
    delete_steps = [step for step in plan.steps if isinstance(step, DeleteFieldsStep)]
    if not (
        len(enum_steps) == len(mapping_steps) == len(add_steps) == len(fill_steps) == 1
        and len(delete_steps) <= 1
        and len(plan.steps) == 4 + len(delete_steps)
    ):
        return plan

    enum_step, mapping_step = enum_steps[0], mapping_steps[0]
    add_step, fill_step = add_steps[0], fill_steps[0]
    if not (
        mapping_step.source_ref == f"step:{enum_step.step_id}"
        and add_step.field_value == f"%{{{enum_step.target_field}}}"
        and fill_step.source_ref == f"step:{mapping_step.step_id}"
        and add_step.config_ref == fill_step.config_ref == CHAIN_CONFIG_REF
    ):
        return plan

    compiled = build_threat_source_plan(
        session, enum_step.target_field, plan_id=plan.plan_id
    )
    if compiled is None:
        return plan
    logger.info(
        "[THREAT_CHAIN] 显式来源计划已编译: source=%s steps=%s",
        enum_step.target_field,
        [step.type for step in compiled.steps],
    )
    return plan.model_copy(update={"steps": compiled.steps})


def build_threat_source_plan(
    session: SessionState, source_field: str, *, plan_id: str
) -> PlanDecision | None:
    """按当前真实配置为一个明确来源构造原子威胁类型链路。"""
    facts = build_session_facts(session)
    threat_rule_names = tuple(
        item.rule_name
        for item in facts.event_annotations
        if item.event_name in THREAT_EVENT_NAMES
    )
    if not threat_rule_names:
        return None
    field_state = inspect_threat_field_state(
        session.mapped_sub_rules, threat_rule_names
    )
    chain = build_threat_chain_steps(
        SourceFieldDecision(source_field, 1.0, len(threat_rule_names), "explicit"),
        config_ref=CHAIN_CONFIG_REF,
        threat_field_state=field_state,
    )
    return PlanDecision(decision="execute", plan_id=plan_id, steps=chain.steps)


@contextmanager
def _stage_span(stage: str) -> Iterator[None]:
    """在既有 TraceContext 下为链路阶段开子 span；无上下文时静默直通。"""
    context = TraceContext.get()
    if context is None:
        yield
        return
    with context.span(stage):
        yield


def _summary_result(message: str) -> StepResult:
    """构造链路汇总行（SUCCESS 状态承载 🔗/⚠️ 文案，不降级整体报告）。"""
    return StepResult(
        step_id=SUMMARY_STEP_ID,
        operation_type="threat_chain",
        status=StepStatus.SUCCESS,
        message=message,
    )


def _extended_report(report: ExecutionReport, extra: tuple[StepResult, ...]) -> ExecutionReport:
    """把链路结果追加到主报告（字段映射自身的结果与状态保持不变）。"""
    return ExecutionReport(
        plan_id=report.plan_id,
        results=report.results + extra,
    )


def record_explicit_source_override(
    report: ExecutionReport, plan_steps: tuple[StepSpec, ...], session: SessionState
) -> str | None:
    """显式指令入口成功后记录会话级来源覆盖（用户纠正过 X，此后自动入口直接用）。

    检测形态：计划含 add_fields(威胁类型, reference %{B}) 且该步成功。
    自动链路自身产出的 add_fields 不在本函数扫描范围（只扫主计划步骤）。
    """
    if report.status != StepStatus.SUCCESS:
        return None
    for step in plan_steps:
        if not isinstance(step, AddFieldsStep):
            continue
        if step.field_name != THREAT_TYPE_FIELD or step.value_type != "reference":
            continue
        referenced = step.field_value[2:-1]
        if not referenced:
            continue
        succeeded = any(
            result.step_id == step.step_id and result.status == StepStatus.SUCCESS
            for result in report.results
        )
        if succeeded:
            set_threat_source_override(session, referenced)
            logger.info(
                "[THREAT_CHAIN] S0 会话来源覆盖已记录: override=%s step_id=%s",
                referenced,
                step.step_id,
            )
            return referenced
    return None


def _retrieve_source_candidates(fields: list[str]) -> dict[str, list[tuple[str, float, str, str]]]:
    """对字段池全量字段检索威胁类型候选（黑名单记录按需包含，#173 X 判定）。"""
    return batch_retrieve_candidates_table(fields, include_mapping_excluded=True)


def rank_threat_source_candidates(
    fields: tuple[str, ...], *, limit: int = 3
) -> tuple[str, ...]:
    """从真实共有字段中选最多三个候选，语义分优先、字段名只作破平。"""
    ordered = tuple(dict.fromkeys(fields))
    try:
        table = _retrieve_source_candidates(list(ordered))
    except Exception as error:  # noqa: BLE001 - 检索失败仍可用字段名稳定破平
        logger.warning("[THREAT_CHAIN] 自动来源候选检索失败: %s", type(error).__name__)
        table = {}
    positive = {"alarm": 2, "name": 2, "event": 1, "attack": 1, "threat": 1, "type": 1}
    negative = {"id", "ip", "port", "time", "timestamp", "count", "mac", "addr", "address"}

    def score(item: tuple[int, str]) -> tuple[float, int, int]:
        """返回语义、描述性和原始顺序组成的稳定降序键。"""
        position, field = item
        semantic = max(
            (row[1] for row in table.get(field, ()) if row[0] == THREAT_TYPE_FIELD),
            default=0.0,
        )
        tokens = {
            re.sub(r"\d+$", "", token)
            for token in re.split(r"[^a-z0-9]+", field.lower())
            if token
        }
        lexical = sum(positive.get(token, 0) for token in tokens) - 2 * len(tokens & negative)
        # ponytail: 字段名只用于零分破平；三次保险试跑不足时再引入值画像。
        return semantic, lexical, -position

    ranked = sorted(enumerate(ordered), key=score, reverse=True)
    return tuple(field for _, field in ranked[:limit])


def _determine_source(
    pools: dict[str, tuple[str, ...]],
    trigger: ChainTrigger,
    session: SessionState,
) -> tuple[Any, dict[str, list[tuple[str, float, str, str]]]]:
    """S1：会话覆盖优先，否则相似度最高；检索失败按无候选降级。

    返回判定结论与候选表（自恢复③改选需在同一得分表上取下一候选）。
    """
    override = session.threat_source_field_override
    ordered_fields: list[str] = []
    for indexes in pools.values():
        for index in indexes:
            if index not in ordered_fields:
                ordered_fields.append(index)
    table: dict[str, list[tuple[str, float, str, str]]] = {}
    if ordered_fields:
        try:
            table = _retrieve_source_candidates(ordered_fields)
        except Exception as error:  # noqa: BLE001 - 检索失败降级，不阻断字段映射
            logger.error(
                "[THREAT_CHAIN] S1 候选检索失败，走降级: error=%s fields=%s",
                type(error).__name__,
                ordered_fields[:10],
            )
            table = {}
    if logger.isEnabledFor(10):  # DEBUG：全量候选得分排序表（选字段唯一事后证据）
        scored_rows = sorted(
            (
                field,
                max(
                    (row[1] for row in rows if row[0] == THREAT_TYPE_FIELD),
                    default=0.0,
                ),
            )
            for field, rows in table.items()
        )
        logger.debug(
            "[THREAT_CHAIN] S1 候选得分表: threat_rules=%s covering_scores=%s",
            list(trigger.threat_rule_names),
            scored_rows,
        )
    decision = determine_source_field(pools, table, override=override)
    logger.info(
        "[THREAT_CHAIN] S1 来源判定完成: field=%s score=%.2f covered=%s reason=%s override=%s",
        decision.source_field,
        decision.score,
        decision.covered_rules,
        decision.reason,
        override,
    )
    return decision, table


def _chain_summary(
    plan: ThreatChainPlan,
    chain_results: tuple[StepResult, ...],
    elapsed: float,
    *,
    note: str = "",
    force_warning: bool = False,
) -> str:
    """S6：汇总链路形态与结果（成功 🔗 / 未完全成功 ⚠️，含失败原因）。"""
    failures = [
        result for result in chain_results if result.status != StepStatus.SUCCESS
    ]
    all_success = not failures
    icon = "🔗" if all_success and not force_warning else "⚠️"
    parts = list(plan.summary_parts)
    if plan.skipped_add_reason:
        parts.append(plan.skipped_add_reason)
    degraded = [
        result
        for result in chain_results
        if result.status == StepStatus.SUCCESS and "已降级" in (result.message or "")
    ]
    if degraded:
        parts.append(f"{len(degraded)} 步结果已降级为「其他」（#394）")
    if all_success:
        parts.append(f"耗时 {elapsed:.1f}s")
    else:
        first = failures[0]
        detail = first.message or first.error_code or "未知原因"
        parts.append(
            f"第 {chain_results.index(first) + 1} 步失败（{first.error_code or first.status}）：{detail}"
        )
        parts.append("字段映射结果不受影响，可用显式指令重试链路")
    if note:
        parts.append(note)
    headline = "威胁类型链路已自动完成" if all_success else "威胁类型链路未完全成功"
    return f"{icon} {headline}：" + "；".join(part for part in parts if part)


async def run_threat_chain_after_mapping(
    *,
    report: Any,
    plan_steps: tuple[StepSpec, ...] = (),
    session: SessionState,
    team: Any,
    progress_sink: ProgressSink | None = None,
    recovery_budget: RecoveryBudget | None = None,
) -> Any:
    """字段映射成功后的执行后确定性续跑入口（S0-S6）。

    非 ExecutionReport（澄清/引导决策）原样返回；链路任何失败都不改变
    主报告的结果行与整体状态，只追加成功步骤行与汇总行。
    recovery_budget 控制自恢复预算（含 ③ 改选次数），None 用默认预算。
    """
    if not isinstance(report, ExecutionReport):
        return report
    with _stage_span("threat_chain"):
        return await _run_chain(
            report, plan_steps, session, team, progress_sink, recovery_budget
        )


async def _run_chain(
    report: ExecutionReport,
    plan_steps: tuple[StepSpec, ...],
    session: SessionState,
    team: Any,
    progress_sink: ProgressSink | None,
    recovery_budget: RecoveryBudget | None,
) -> ExecutionReport:
    """链路主体（S0-S6 + 自恢复③改选，stage span 内执行）。"""
    started = time.monotonic()

    # S0 触发判定：显式来源覆盖记录 + 威胁子规则判定
    record_explicit_source_override(report, plan_steps, session)
    trigger = evaluate_chain_trigger(report.results)
    if trigger is None:
        return report
    logger.info(
        "[THREAT_CHAIN] S0 触发判定: threat_rules=%s uncertain_rules=%s",
        list(trigger.threat_rule_names),
        list(trigger.uncertain_rule_names),
    )
    if trigger.hint_only:
        report = refresh_report_event_annotations(
            report,
            session.mapped_sub_rules,
            chain_succeeded=False,
        )
        return _extended_report(
            report,
            (
                _summary_result(
                    f"⚠️ 检测到 {len(trigger.uncertain_rule_names)} 条子规则的事件名称待人工确认，"
                    "威胁类型链路未自动执行；确认标注后重新执行标准字段映射即可触发。"
                ),
            ),
        )

    mapped_rules = session.mapped_sub_rules
    pools = collect_threat_field_pools(mapped_rules, trigger.threat_rule_names)
    if not pools:
        logger.error(
            "[THREAT_CHAIN] S0 威胁子规则未在 mapped_sub_rules 中找到: rules=%s",
            list(trigger.threat_rule_names),
        )
        refreshed = refresh_report_event_annotations(
            report, mapped_rules, chain_succeeded=False
        )
        return _extended_report(
            refreshed,
            (_summary_result("⚠️ 威胁类型链路未执行：威胁子规则状态异常（mapped_sub_rules 缺失）"),),
        )

    # S1 来源字段判定
    with _stage_span("threat_chain_s1_source"):
        decision, candidate_table = _determine_source(pools, trigger, session)

    # 构造（含 S4 分支：absent/chain/existing 决定加删跳过）
    threat_field_state = inspect_threat_field_state(mapped_rules, trigger.threat_rule_names)
    plan = build_threat_chain_steps(
        decision,
        config_ref=CHAIN_CONFIG_REF,
        threat_field_state=threat_field_state,
    )
    logger.info(
        "[THREAT_CHAIN] S1 链路形态: degraded=%s threat_field_state=%s steps=%s",
        plan.degraded,
        threat_field_state,
        [step.type for step in plan.steps],
    )

    # S2-S5 经统一执行器续跑（每步进度事件自动进入同一进度账本）
    chain_budget = recovery_budget or RecoveryBudget()
    chain_decision = PlanDecision(
        decision="execute",
        plan_id=CHAIN_PLAN_ID,
        steps=plan.steps,
    )
    staged_session = stage_threat_chain_session(session)
    with _stage_span("threat_chain_s2_s5_execute"):
        try:
            chain_report = await create_plan_executor(
                create_default_adapters(team)
            ).execute(
                chain_decision,
                ExecutionContext(
                    session=staged_session,
                    session_facts=build_session_facts(staged_session),
                    progress_sink=progress_sink or NullProgressSink(),
                    recovery_budget=chain_budget,
                ),
            )
        except Exception as error:  # noqa: BLE001 - 链路异常不波及字段映射结果
            logger.error(
                "[THREAT_CHAIN] S2-S5 执行异常: error=%s plan_id=%s",
                type(error).__name__,
                CHAIN_PLAN_ID,
            )
            refreshed = refresh_report_event_annotations(
                report, mapped_rules, chain_succeeded=False
            )
            return _extended_report(
                refreshed,
                (
                    _summary_result(
                        f"⚠️ 威胁类型链路执行异常（{type(error).__name__}），"
                        "字段映射结果不受影响；可用显式指令重试链路"
                    ),
                ),
            )

    if chain_report.status == StepStatus.SUCCESS:
        commit_threat_chain_session(staged_session, session)

    # S5+ 自恢复③（#225 / ADR-0011）：自动判定的来源字段结果全落「其他」（无信息量）
    # 时，从 S1 得分表确定性改选下一覆盖候选重跑一次。用户指定或会话级纠正过的来源
    # 不参与；预算 0 保持现状。ponytail: 阈值 1.0 是最保守启发式，若门禁数据显示
    # 80% 落「其他」也应改选，再调；LLM 判断的升级路径见 ADR-0011。
    rederive_note = ""
    gate_blocked = False
    mapped_values = [
        row.mapped_value
        for result in chain_report.results
        if isinstance(result.artifact, ThreatMappingArtifact)
        for row in result.artifact.mappings
    ]
    if (
        chain_report.status == StepStatus.SUCCESS
        and chain_budget.max_rederive > 0
        and should_rederive(mapped_values, source_reason=decision.reason)
    ):
        next_decision = determine_source_field(
            pools, candidate_table, exclude=(decision.source_field,)
        )
        if next_decision.source_field is None:
            logger.info(
                "[THREAT_CHAIN] 自恢复③无下一覆盖候选，保持现状: old_source=%s",
                decision.source_field,
            )
        else:
            # 按提交后的最新配置重建（首次成功已改变威胁类型字段现状，幂等语义自带）
            next_state = inspect_threat_field_state(
                session.mapped_sub_rules,
                trigger.threat_rule_names,
            )
            next_plan = build_threat_chain_steps(
                next_decision,
                config_ref=CHAIN_CONFIG_REF,
                threat_field_state=next_state,
            )
            if not is_safe_rederive_plan(next_plan.steps):
                rederive_note = "改选重跑未通过不可逆门禁，已放弃自动改选"
                gate_blocked = True
                logger.error(
                    "[THREAT_CHAIN] 自恢复③不可逆门禁拦截: old_source=%s new_source=%s",
                    decision.source_field,
                    next_decision.source_field,
                )
            else:
                restaged_session = stage_threat_chain_session(session)
                rerun_report: ExecutionReport | None = None
                with _stage_span("threat_chain_rederive"):
                    try:
                        rerun_report = await create_plan_executor(
                            create_default_adapters(team)
                        ).execute(
                            PlanDecision(
                                decision="execute",
                                plan_id=CHAIN_PLAN_ID,
                                steps=next_plan.steps,
                            ),
                            ExecutionContext(
                                session=restaged_session,
                                session_facts=build_session_facts(restaged_session),
                                progress_sink=progress_sink or NullProgressSink(),
                                recovery_budget=chain_budget,
                            ),
                        )
                    except Exception as error:  # noqa: BLE001 - 重跑异常保留首次结果
                        logger.error(
                            "[THREAT_CHAIN] 自恢复③重跑异常: error=%s",
                            type(error).__name__,
                        )
                recovery_logger.info(
                    "[RECOVERY] plan_id=%s step_id=%s type=rederive old_source=%s "
                    "new_source=%s other_ratio=%.2f result=%s",
                    CHAIN_PLAN_ID,
                    SUMMARY_STEP_ID,
                    decision.source_field,
                    next_decision.source_field,
                    degraded_mapping_ratio(mapped_values),
                    rerun_report.status.value
                    if rerun_report is not None
                    else "exception",
                )
                if rerun_report is not None and rerun_report.status == StepStatus.SUCCESS:
                    commit_threat_chain_session(restaged_session, session)
                    plan = next_plan
                    chain_report = rerun_report
                    rerun_values = [
                        row.mapped_value
                        for result in rerun_report.results
                        if isinstance(result.artifact, ThreatMappingArtifact)
                        for row in result.artifact.mappings
                    ]
                    # 第二次执行成功但仍全落「其他」：保持降级现状，不再重试
                    still_degraded = degraded_mapping_ratio(rerun_values) >= 1.0
                    rederive_note = (
                        f"来源字段已自动改选 {decision.source_field} → "
                        f"{next_decision.source_field}"
                        + ("，结果仍全为「其他」，保持降级" if still_degraded else "")
                    )
                    logger.info(
                        "[THREAT_CHAIN] 自恢复③改选重跑完成: old_source=%s "
                        "new_source=%s still_degraded=%s",
                        decision.source_field,
                        next_decision.source_field,
                        still_degraded,
                    )
                else:
                    # 重跑执行失败：保留首次已提交结果，不再重试
                    rederive_note = (
                        f"已自动改选 {decision.source_field} → "
                        f"{next_decision.source_field} 重跑，未获得更好结果，保留首次结果"
                    )

    report = refresh_report_event_annotations(
        report,
        session.mapped_sub_rules,
        chain_succeeded=chain_report.status == StepStatus.SUCCESS,
    )

    # S6 汇总：只追加成功步骤行（失败不降级主报告状态），汇总行说明全貌
    elapsed = time.monotonic() - started
    summary = _chain_summary(
        plan,
        chain_report.results,
        elapsed,
        note=rederive_note,
        force_warning=gate_blocked,
    )
    logger.info(
        "[THREAT_CHAIN] S6 链路结束: status=%s elapsed=%.1fs result_count=%s",
        chain_report.status,
        elapsed,
        len(chain_report.results),
    )
    successful = tuple(
        result for result in chain_report.results if result.status == StepStatus.SUCCESS
    )
    return _extended_report(report, successful + (_summary_result(summary),))
