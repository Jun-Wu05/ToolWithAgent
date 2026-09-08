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
import time
from contextlib import contextmanager
from typing import Any, Iterator

from agent.core.field_retriever import batch_retrieve_candidates_table
from agent.core.tracing import TraceContext
from agent.shared.logger import get_logger
from application.adapters.composition import create_default_adapters
from application.adapters.shared import _session_get, _session_set
from application.execution import ExecutionContext
from application.execution_policy import create_plan_executor
from application.progress import NullProgressSink
from application.session_projection import build_session_facts
from application.threat_chain_policy import (
    ChainTrigger,
    ThreatChainPlan,
    build_threat_chain_steps,
    collect_threat_field_pools,
    determine_source_field,
    evaluate_chain_trigger,
    inspect_threat_field_state,
)
from contracts.planner_models import (
    AddFieldsStep,
    ExecutionReport,
    FillStep,
    PlanDecision,
    StepResult,
    StepStatus,
    StepSpec,
    THREAT_TYPE_FIELD,
)
from contracts.progress import ProgressSink

logger = get_logger("threat_chain")

CHAIN_PLAN_ID = "threat-chain-auto"
"""链路续跑计划 ID（进度与日志可按此归组）。"""

SUMMARY_STEP_ID = "threat-chain"
"""链路汇总行的 step_id（渲染为报告末尾的 🔗/⚠️ 段落）。"""

SESSION_OVERRIDE_KEY = "threat_source_field_override"
"""会话级来源覆盖键（#129 临时字段模式）：用户显式纠正过 X 后记忆。"""

CHAIN_CONFIG_REF = "session.mapped_sub_rules"
"""自动链路的目标配置：事件标注所在处（mapped_sub_rules）。"""

_CHAIN_COMMIT_KEYS = (
    "mapped_sub_rules",
    "last_enum_extract_result",
    "latest_enum_artifact",
    "last_threat_data",
    "latest_threat_artifact",
)
"""威胁链成功后才从配置副本会话提交的领域产物。"""


def stage_threat_chain_session(session: Any) -> Any:
    """为威胁链构造隔离会话，其他输入只读共享、目标配置深拷贝。"""
    staged = dict(session) if isinstance(session, dict) else copy.copy(session)
    _session_set(
        staged,
        "mapped_sub_rules",
        copy.deepcopy(_session_get(session, "mapped_sub_rules")),
    )
    return staged


def commit_threat_chain_session(staged: Any, session: Any) -> None:
    """整条链成功后一次性提交配置与可引用产物。"""
    for key in _CHAIN_COMMIT_KEYS:
        _session_set(session, key, _session_get(staged, key))


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
    report: ExecutionReport, plan_steps: tuple[StepSpec, ...], session: Any
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
            _session_set(session, SESSION_OVERRIDE_KEY, referenced)
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


def _determine_source(
    pools: dict[str, tuple[str, ...]],
    trigger: ChainTrigger,
    session: Any,
) -> tuple[Any, str]:
    """S1：会话覆盖优先，否则相似度最高；检索失败按无候选降级。"""
    override = _session_get(session, SESSION_OVERRIDE_KEY)
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
    return decision, override or ""


def _chain_summary(
    plan: ThreatChainPlan, chain_results: tuple[StepResult, ...], elapsed: float
) -> str:
    """S6：汇总链路形态与结果（成功 🔗 / 未完全成功 ⚠️，含失败原因）。"""
    failures = [
        result for result in chain_results if result.status != StepStatus.SUCCESS
    ]
    all_success = not failures
    icon = "🔗" if all_success else "⚠️"
    parts = list(plan.summary_parts)
    if plan.skipped_add_reason:
        parts.append(plan.skipped_add_reason)
    if all_success:
        parts.append(f"耗时 {elapsed:.1f}s")
    else:
        first = failures[0]
        detail = first.message or first.error_code or "未知原因"
        parts.append(
            f"第 {chain_results.index(first) + 1} 步失败（{first.error_code or first.status}）：{detail}"
        )
        parts.append("字段映射结果不受影响，可用显式指令重试链路")
    headline = "威胁类型链路已自动完成" if all_success else "威胁类型链路未完全成功"
    return f"{icon} {headline}：" + "；".join(part for part in parts if part)


async def run_threat_chain_after_mapping(
    *,
    report: Any,
    plan_steps: tuple[StepSpec, ...] = (),
    session: Any,
    team: Any,
    progress_sink: ProgressSink | None = None,
) -> Any:
    """字段映射成功后的执行后确定性续跑入口（S0-S6）。

    非 ExecutionReport（澄清/引导决策）原样返回；链路任何失败都不改变
    主报告的结果行与整体状态，只追加成功步骤行与汇总行。
    """
    if not isinstance(report, ExecutionReport):
        return report
    with _stage_span("threat_chain"):
        return await _run_chain(report, plan_steps, session, team, progress_sink)


async def _run_chain(
    report: ExecutionReport,
    plan_steps: tuple[StepSpec, ...],
    session: Any,
    team: Any,
    progress_sink: ProgressSink | None,
) -> ExecutionReport:
    """链路主体（S0-S6，stage span 内执行）。"""
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
        return _extended_report(
            report,
            (
                _summary_result(
                    f"⚠️ 检测到 {len(trigger.uncertain_rule_names)} 条子规则的事件名称待人工确认，"
                    "威胁类型链路未自动执行；确认标注后重新执行标准字段映射即可触发。"
                ),
            ),
        )

    mapped_rules = _session_get(session, "mapped_sub_rules")
    pools = collect_threat_field_pools(mapped_rules, trigger.threat_rule_names)
    if not pools:
        logger.error(
            "[THREAT_CHAIN] S0 威胁子规则未在 mapped_sub_rules 中找到: rules=%s",
            list(trigger.threat_rule_names),
        )
        return _extended_report(
            report,
            (_summary_result("⚠️ 威胁类型链路未执行：威胁子规则状态异常（mapped_sub_rules 缺失）"),),
        )

    # S1 来源字段判定
    with _stage_span("threat_chain_s1_source"):
        decision, _override = _determine_source(pools, trigger, session)

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
                ),
            )
        except Exception as error:  # noqa: BLE001 - 链路异常不波及字段映射结果
            logger.error(
                "[THREAT_CHAIN] S2-S5 执行异常: error=%s plan_id=%s",
                type(error).__name__,
                CHAIN_PLAN_ID,
            )
            return _extended_report(
                report,
                (
                    _summary_result(
                        f"⚠️ 威胁类型链路执行异常（{type(error).__name__}），"
                        "字段映射结果不受影响；可用显式指令重试链路"
                    ),
                ),
            )

    if chain_report.status == StepStatus.SUCCESS:
        commit_threat_chain_session(staged_session, session)

    # S6 汇总：只追加成功步骤行（失败不降级主报告状态），汇总行说明全貌
    elapsed = time.monotonic() - started
    summary = _chain_summary(plan, chain_report.results, elapsed)
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
