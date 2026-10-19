"""统一计划执行核心：校验、解析依赖、推进步骤并验证本次结果。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Protocol, get_args

from contracts.planner_models import (
    ConfigRef,
    EnumExtractStep,
    DeterministicPlan,
    ExecutionReport,
    ExportStep,
    FieldMappingStep,
    FillStep,
    LogParseStep,
    PlanDecision,
    RemoveMappingStep,
    StepResult,
    StepSpec,
    ExecutableStep,
    StepStatus,
    THREAT_TYPE_FIELD,
    ThreatMappingStep,
)
from application.progress import NullProgressSink
from application.execution_continuation import ExecutionContinuation
from application.session_state import SessionState
from application.recovery import RecoveryBudget, RETRYABLE_STEP_TYPES, is_transient
from contracts.progress import (
    ProgressEvent,
    ProgressPhase,
    ProgressSink,
    ProgressStatus,
)
from contracts.session_facts import SessionFacts
from contracts.session_artifacts import EnumArtifactSlot, ThreatArtifactSlot

# ConfigRef 词汇表成员判定；与 adapters.shared._CONFIG_SESSION_KEYS 的键集由
# test_application_config_architecture 双向钉死（#350）。此处不导入
# adapters.shared——shared 反向依赖本模块的 ExecutionContext，会成环。
_CONFIG_REFS = frozenset(get_args(ConfigRef))


def threat_fill_source_precondition(
    step: ExecutableStep, session: SessionState
) -> tuple[Any | None, StepResult | None]:
    """威胁映射填充「产物可用 + 固定目标」的唯一前置校验（#314 单一来源）。

    执行器预检与 ThreatFillAdapter 共同消费：拦截结果非 None 时调用方必须
    原样返回；通过时返回已验证的产物槽（非威胁映射来源返回 (None, None)，
    由调用方走依赖产物分支）。判定基于 session 槽 latest_threat_artifact 的
    解析结果——与 referenceable_artifacts 投影恒等（投影即由该槽解析生成）。
    填充目标恒为「威胁类型」（#173 修复 1）：不按 source_field 血缘推导，
    字段映射改判不会使目标静默漂移；用户显式点名其他字段由 Planner 澄清拦截。
    """
    if step.source_ref != "session.artifacts.threat_mapping":
        return None, None
    raw_slot = session.latest_threat_artifact
    try:
        slot = (
            raw_slot
            if isinstance(raw_slot, ThreatArtifactSlot)
            else ThreatArtifactSlot.model_validate(raw_slot)
        )
    except (TypeError, ValueError):
        return None, PlanExecutor._needs_input_result(
            step,
            "artifact_source_unavailable",
            "最近威胁映射产物已不可用，请重新执行威胁映射",
        )
    if step.target_fields != (THREAT_TYPE_FIELD,):
        return None, PlanExecutor._needs_input_result(
            step,
            "threat_fill_target_fixed",
            f"威胁映射只能填充到固定目标字段「{THREAT_TYPE_FIELD}」",
        )
    return slot, None


def threat_mapping_source_precondition(
    step: ExecutableStep, session: SessionState
) -> tuple[Any | None, StepResult | None]:
    """威胁类型映射「枚举值产物可用」的唯一前置校验（#320 单一来源）。

    执行器预检与 ThreatMappingAdapter 共同消费：拦截结果非 None 时调用方
    必须原样返回；通过时返回已验证的枚举产物槽（非枚举产物来源返回
    (None, None)，由调用方走 user.values / step: 依赖分支）。判定基于
    session 槽 latest_enum_artifact 的解析结果——与 referenceable_artifacts
    投影恒等（投影即由该槽解析生成）。
    """
    if step.source_ref != "session.artifacts.enum_values":
        return None, None
    raw_slot = session.latest_enum_artifact
    try:
        slot = (
            raw_slot
            if isinstance(raw_slot, EnumArtifactSlot)
            else EnumArtifactSlot.model_validate(raw_slot)
        )
    except (TypeError, ValueError):
        return None, PlanExecutor._needs_input_result(
            step,
            "artifact_source_unavailable",
            "最近枚举值产物已不可用，请重新提取枚举值",
        )
    return slot, None


@dataclass(frozen=True)
class ExecutionContext:
    """保存执行期 session 与其单一事实快照；核心模块不依赖 Chainlit。"""

    session: SessionState
    session_facts: SessionFacts
    plan_id: str = "pending"
    progress_sink: ProgressSink = field(default_factory=NullProgressSink)
    recovery_budget: RecoveryBudget = field(default_factory=RecoveryBudget)
    checkpoint: dict | None = None


class StepAdapter(Protocol):
    """规定专业执行适配器的唯一职责和类型化输入输出。"""

    async def execute(
        self,
        step: ExecutableStep,
        context: ExecutionContext,
        dependencies: Mapping[str, StepResult],
    ) -> StepResult:
        """执行单一步骤，不得理解用户原文或读取未声明依赖。"""


class ExecutionPolicy(Protocol):
    """在执行接缝注入领域预检，避免核心依赖具体领域实现。"""

    def validate_plan(
        self, plan: PlanDecision | DeterministicPlan, context: ExecutionContext
    ) -> tuple[ExecutableStep, StepResult] | None:
        """在任何步骤写入前校验整份计划。"""

    def validate_step(
        self,
        step: ExecutableStep,
        context: ExecutionContext,
        ledger: Mapping[str, StepResult],
    ) -> StepResult | None:
        """在单步 Adapter 执行前校验领域语义。"""


class NullExecutionPolicy:
    """无额外领域规则时使用的框架无关策略。"""

    def validate_plan(
        self, plan: PlanDecision | DeterministicPlan, context: ExecutionContext
    ) -> tuple[ExecutableStep, StepResult] | None:
        return None

    def validate_step(
        self,
        step: ExecutableStep,
        context: ExecutionContext,
        ledger: Mapping[str, StepResult],
    ) -> StepResult | None:
        return None


class PlanExecutor:
    """按计划顺序执行步骤，并在首个失败或待输入状态后立即停止。"""

    def __init__(
        self,
        adapters: Mapping[str, StepAdapter],
        *,
        policy: ExecutionPolicy | None = None,
        logger: logging.Logger | None = None,
        recovery_logger: logging.Logger | None = None,
    ) -> None:
        """接收按操作类型注册的适配器；缺失适配器属于稳定执行错误。"""
        self._adapters = dict(adapters)
        self._policy = policy or NullExecutionPolicy()
        self._logger = logger or logging.getLogger("plan_executor")
        self._recovery_logger = recovery_logger or logging.getLogger("recovery")

    async def execute(
        self,
        plan: PlanDecision | DeterministicPlan,
        context: ExecutionContext,
        *,
        continuation: ExecutionContinuation | None = None,
    ) -> ExecutionReport:
        """执行已校验计划并返回本次步骤账本，绝不回退到关键词路由。"""
        if plan.decision != "execute":
            raise ValueError("PlanExecutor 只接受 execute 决策")

        context = replace(context, plan_id=plan.plan_id)
        await context.progress_sink.publish(
            ProgressEvent(
                plan_id=plan.plan_id,
                step_id="plan",
                phase=ProgressPhase.EXECUTION,
                status=ProgressStatus.RUNNING,
                message_code="plan_execution_started",
            )
        )

        self._logger.info(
            "[EXECUTOR] 计划开始: plan_id=%s step_count=%s available_config_refs=%s "
            "has_logs=%s available_field_count=%s mappable_field_count=%s "
            "enum_target_field_count=%s",
            plan.plan_id,
            len(plan.steps),
            list(context.session_facts.available_config_refs),
            context.session_facts.has_logs,
            len(context.session_facts.available_fields),
            len(context.session_facts.mappable_fields),
            len(context.session_facts.enum_mapping_target_fields),
        )
        restored = []
        if continuation is not None:
            if continuation.frozen_plan != plan.model_dump(mode="json"):
                raise ValueError("continuation_plan_mismatch")
            restored = [StepResult.model_validate(value) for value in continuation.completed_results]
            if tuple(result.step_id for result in restored) != continuation.completed_step_refs:
                raise ValueError("continuation_ledger_invalid")
            if len(restored) > len(plan.steps) or any(
                result.status != StepStatus.SUCCESS or result.step_id != step.step_id
                or result.operation_type != step.type
                for result, step in zip(restored, plan.steps)
            ):
                raise ValueError("continuation_ledger_invalid")
        ledger: dict[str, StepResult] = {result.step_id: result for result in restored}
        ordered_results: list[StepResult] = list(restored)
        recovery_count = continuation.recovery_count if continuation else 0
        step_recovery_counts: dict[str, int] = dict(continuation.step_recovery_counts) if continuation else {}
        if continuation is not None:
            context = replace(context, recovery_budget=RecoveryBudget(**continuation.recovery_budget))
        # 计划级预校验（#148）：事件名的确定性非法值必须在**任何步骤执行前**拦截
        # 整份计划——改名 delete+add 两步中，add 的非法事件名若等到执行期才拒绝，
        # 前面的 delete 已联动删除绑定对并写盘，无法回滚。
        plan_level_block = self._policy.validate_plan(plan, context)
        if plan_level_block is not None:
            blocked_step, blocked_result = plan_level_block
            ordered_results.append(blocked_result)
            await self._publish_step_terminal(
                plan.plan_id,
                blocked_step,
                blocked_result,
                context.progress_sink,
            )
            self._logger.info(
                "[EXECUTOR] 计划级拦截: plan_id=%s step_id=%s operation=%s status=%s "
                "error_category=%s declared_step_count=%s",
                plan.plan_id,
                blocked_step.step_id,
                blocked_step.type,
                blocked_result.status.value,
                blocked_result.error_code,
                len(plan.steps),
            )
        for step in (plan.steps if plan_level_block is None else ()):
            if step.step_id in ledger:
                continue  # 恢复成功前缀账本，保留 step: 依赖且不重复执行。
            await context.progress_sink.publish(
                ProgressEvent(
                    plan_id=plan.plan_id,
                    step_id=step.step_id,
                    phase=ProgressPhase.EXECUTION,
                    status=ProgressStatus.RUNNING,
                    message_code=f"{step.type}_started",
                    dependency_step_ids=step.depends_on,
                )
            )
            self._logger.info(
                "[EXECUTOR_STEP] 步骤开始: plan_id=%s step_id=%s operation=%s "
                "source_ref=%s config_ref=%s target_field_count=%s dependency_count=%s",
                plan.plan_id,
                step.step_id,
                step.type,
                getattr(step, "source_ref", "none"),
                getattr(step, "config_ref", "none"),
                len(getattr(step, "target_fields", ()))
                + int(bool(getattr(step, "target_field", None))),
                len(step.depends_on),
            )
            preflight_error = self._validate_step(step, context, ledger)
            if preflight_error is None:
                preflight_error = self._policy.validate_step(step, context, ledger)
            if preflight_error is not None:
                ordered_results.append(preflight_error)
                await self._publish_step_terminal(
                    plan.plan_id,
                    step,
                    preflight_error,
                    context.progress_sink,
                )
                self._logger.info(
                    "[EXECUTOR] 执行前拦截: plan_id=%s step_id=%s operation=%s status=%s "
                    "error_category=%s required_config_ref=%s observed_config_refs=%s "
                    "has_logs=%s available_field_count=%s mappable_field_count=%s "
                    "enum_target_field_count=%s",
                    plan.plan_id,
                    step.step_id,
                    step.type,
                    preflight_error.status.value,
                    preflight_error.error_code,
                    getattr(step, "config_ref", "none"),
                    list(context.session_facts.available_config_refs),
                    context.session_facts.has_logs,
                    len(context.session_facts.available_fields),
                    len(context.session_facts.mappable_fields),
                    len(context.session_facts.enum_mapping_target_fields),
                )
                break

            resumable_failure = False
            adapter = self._adapters.get(step.type)
            if adapter is None:
                result = self._error_result(step, "adapter_unavailable", "当前操作尚未配置执行适配器")
            else:
                dependencies = {step_id: ledger[step_id] for step_id in step.depends_on}
                trigger_error_code: str | None = None
                while True:
                    execution_error: Exception | None = None
                    try:
                        result = await adapter.execute(step, context, dependencies)
                        result = self._validate_result(step, result)
                    except Exception as error:
                        execution_error = error
                        self._logger.exception(
                            "[EXECUTOR] 步骤异常: plan_id=%s step_id=%s operation=%s "
                            "error_category=adapter_failed",
                            plan.plan_id,
                            step.step_id,
                            step.type,
                        )
                        result = self._error_result(
                            step, "adapter_failed", "执行适配器发生异常"
                        )
                    step_recovery_count = step_recovery_counts.get(step.step_id, 0)
                    budget = context.recovery_budget
                    transient_failure = step.type in RETRYABLE_STEP_TYPES and is_transient(
                        execution_error if execution_error is not None else result)
                    resumable_failure = transient_failure and (
                        recovery_count >= budget.max_per_plan or step_recovery_count >= budget.max_per_step)
                    if not (
                        step.type in RETRYABLE_STEP_TYPES
                        and recovery_count < budget.max_per_plan
                        and step_recovery_count < budget.max_per_step
                        and is_transient(
                            execution_error if execution_error is not None else result
                        )
                    ):
                        break
                    trigger_error_code = result.error_code or "adapter_failed"
                    recovery_count += 1
                    step_recovery_counts[step.step_id] = step_recovery_count + 1
                if trigger_error_code is not None:
                    result = result.model_copy(update={"recovered": True})
                    self._recovery_logger.info(
                        "[RECOVERY] plan_id=%s step_id=%s type=retry error_code=%s "
                        "result=%s plan_recovery_count=%s/%s",
                        plan.plan_id,
                        step.step_id,
                        trigger_error_code,
                        result.status.value,
                        recovery_count,
                        budget.max_per_plan,
                    )

            ledger[step.step_id] = result
            ordered_results.append(result)
            if context.checkpoint is not None:
                context.checkpoint.update({
                    "resumable_failure": resumable_failure,
                    "recovery_budget": {"max_per_plan": context.recovery_budget.max_per_plan,
                        "max_per_step": context.recovery_budget.max_per_step, "max_rederive": context.recovery_budget.max_rederive},
                    "recovery_count": recovery_count,
                    "step_recovery_counts": dict(step_recovery_counts),
                    "completed_results": [item.model_dump(mode="json") for item in ordered_results if item.status == StepStatus.SUCCESS],
                })
            await self._publish_step_terminal(
                plan.plan_id,
                step,
                result,
                context.progress_sink,
            )
            self._logger.info(
                "[EXECUTOR] 步骤结束: plan_id=%s step_id=%s operation=%s status=%s "
                "error_category=%s changed_count=%s artifact_type=%s artifact_item_count=%s",
                plan.plan_id,
                step.step_id,
                step.type,
                result.status.value,
                result.error_code or "none",
                result.changed_count,
                getattr(result.artifact, "artifact_type", "none"),
                getattr(result.artifact, "item_count", 0),
            )
            if result.status != StepStatus.SUCCESS:
                break

        execution_report = ExecutionReport(plan_id=plan.plan_id, results=tuple(ordered_results))
        await context.progress_sink.publish(
            ProgressEvent(
                plan_id=plan.plan_id,
                step_id="plan",
                phase=ProgressPhase.COMPLETED,
                status=(
                    ProgressStatus.SUCCESS
                    if execution_report.status == StepStatus.SUCCESS
                    else ProgressStatus.FAILED
                ),
                message_code=f"plan_{execution_report.status.value}",
            )
        )
        self._logger.info(
            "[EXECUTOR] 计划结束: plan_id=%s status=%s completed_step_count=%s "
            "declared_step_count=%s",
            plan.plan_id,
            execution_report.status.value,
            len(execution_report.results),
            len(plan.steps),
        )
        return execution_report

    async def execute_deterministic(
        self,
        plan: DeterministicPlan,
        context: ExecutionContext,
    ) -> ExecutionReport:
        """执行可信按钮构造的计划，并复用同一校验、进度、账本和分派链。"""
        return await self.execute(plan, context)

    @staticmethod
    async def _publish_step_terminal(
        plan_id: str,
        step: ExecutableStep,
        result: StepResult,
        progress_sink: ProgressSink,
    ) -> None:
        """为每个业务步骤发布终态，使界面保留完整步骤账本。"""
        is_success = result.status == StepStatus.SUCCESS
        await progress_sink.publish(
            ProgressEvent(
                plan_id=plan_id,
                step_id=step.step_id,
                phase=ProgressPhase.COMPLETED,
                status=(
                    ProgressStatus.SUCCESS
                    if is_success
                    else ProgressStatus.FAILED
                ),
                dependency_step_ids=step.depends_on,
                message_code=(
                    f"{step.type}_completed"
                    if is_success
                    else f"{step.type}_{result.status.value}"
                ),
            )
        )

    def _validate_step(
        self,
        step: ExecutableStep,
        context: ExecutionContext,
        ledger: Mapping[str, StepResult],
    ) -> StepResult | None:
        """集中执行 session 语义和依赖校验，避免各适配器重复解释状态。"""
        session_facts = context.session_facts
        for dependency_id in step.depends_on:
            dependency = ledger.get(dependency_id)
            if dependency is None:
                return self._error_result(step, "dependency_missing", "声明的步骤依赖不存在")
            if dependency.status != StepStatus.SUCCESS:
                return self._error_result(step, "dependency_failed", "声明的步骤依赖未成功")

        if isinstance(step, LogParseStep) and not session_facts.has_logs:
            return self._needs_input_result(step, "logs_required", "请先上传包含日志的数据")
        if isinstance(step, FieldMappingStep) and not session_facts.mappable_fields:
            all_uploaded_fields_mapped = (
                session_facts.has_decoded_config
                and session_facts.decoded_mapped_field_count > 0
                and session_facts.decoded_unmapped_field_count == 0
            )
            if not all_uploaded_fields_mapped:
                return self._needs_input_result(
                    step, "fields_required", "当前没有可映射的原始字段"
                )
        if (
            isinstance(step, ExportStep)
            and step.source_ref in _CONFIG_REFS
            and step.source_ref not in session_facts.available_config_refs
        ):
            return self._needs_input_result(
                step,
                "config_source_unavailable",
                f"当前没有可导出的配置来源: {step.source_ref}",
            )
        if (
            isinstance(step, ExportStep)
            and step.source_ref.startswith("session.log_classification.")
            and not session_facts.has_log_classification
        ):
            return self._needs_input_result(
                step,
                "log_classification_required",
                "请先完成日志类型提取再导出规则",
            )
        if isinstance(step, RemoveMappingStep) and step.config_ref not in session_facts.available_config_refs:
            return self._needs_input_result(
                step,
                "config_source_unavailable",
                f"当前没有可取消映射的配置来源: {step.config_ref}",
            )
        if isinstance(step, EnumExtractStep):
            if not session_facts.has_logs:
                return self._needs_input_result(step, "logs_required", "请先上传包含日志的数据")
        if (
            isinstance(step, ThreatMappingStep)
            and step.source_ref == "session.artifacts.enum_values"
        ):
            # 前置条件单一来源（#320）：与 ThreatMappingAdapter 消费同一实现。
            _enum_slot, blocked = threat_mapping_source_precondition(
                step, context.session
            )
            if blocked is not None:
                return blocked
        if isinstance(step, FillStep):
            if step.config_ref not in session_facts.available_config_refs:
                return self._needs_input_result(
                    step,
                    "config_source_unavailable",
                    f"当前没有可填充的配置来源: {step.config_ref}",
                )
            if step.fill_kind == "enum" and step.source_ref == "session.enum_mapping_table":
                unavailable = set(step.target_fields) - set(session_facts.enum_mapping_target_fields)
                if unavailable:
                    return self._needs_input_result(
                        step,
                        "mapping_target_unavailable",
                        f"枚举映射表不包含目标字段: {sorted(unavailable)}",
                    )
            if step.source_ref == "session.artifacts.threat_mapping":
                # 前置条件单一来源（#314）：与 ThreatFillAdapter 消费同一实现。
                _threat_slot, blocked = threat_fill_source_precondition(
                    step, context.session
                )
                if blocked is not None:
                    return blocked
        return None

    def _validate_result(self, step: ExecutableStep, result: StepResult) -> StepResult:
        """验证适配器结果属于当前步骤，并阻止填充零变更被静默报告成功。"""
        if result.step_id != step.step_id or result.operation_type != step.type:
            return self._error_result(step, "invalid_step_result", "适配器返回了不匹配的步骤结果")
        if isinstance(step, FillStep) and result.status == StepStatus.SUCCESS and result.changed_count == 0:
            return self._error_result(step, "no_effect", "填充未改变任何目标字段")
        return result

    @staticmethod
    def _error_result(step: ExecutableStep, error_code: str, message: str) -> StepResult:
        """构造稳定失败结果，不携带敏感输入原值。"""
        return StepResult(
            step_id=step.step_id,
            operation_type=step.type,
            status=StepStatus.FAILED,
            error_code=error_code,
            message=message,
        )

    @staticmethod
    def _needs_input_result(step: ExecutableStep, error_code: str, message: str) -> StepResult:
        """构造待输入结果，使调用层明确追问而不是猜测参数。"""
        return StepResult(
            step_id=step.step_id,
            operation_type=step.type,
            status=StepStatus.NEEDS_INPUT,
            error_code=error_code,
            message=message,
        )
