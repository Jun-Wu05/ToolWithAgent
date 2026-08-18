"""统一计划执行核心：校验、解析依赖、推进步骤并验证本次结果。"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Protocol

from agent.shared.logger import get_logger
from contracts.planner_models import (
    EnumExtractStep,
    ExecutionReport,
    ExportStep,
    FieldMappingStep,
    FillStep,
    LogParseStep,
    PlanDecision,
    RemoveMappingStep,
    StepResult,
    StepSpec,
    StepStatus,
)
from contracts.progress import (
    NullProgressSink,
    ProgressEvent,
    ProgressPhase,
    ProgressSink,
    ProgressStatus,
)
from contracts.session_facts import SessionFacts

logger = get_logger("plan_executor")


@dataclass(frozen=True)
class ExecutionContext:
    """保存执行期 session 与其单一事实快照；核心模块不依赖 Chainlit。"""

    session: Any
    session_facts: SessionFacts
    plan_id: str = "pending"
    progress_sink: ProgressSink = field(default_factory=NullProgressSink)


class StepAdapter(Protocol):
    """规定专业执行适配器的唯一职责和类型化输入输出。"""

    async def execute(
        self,
        step: StepSpec,
        context: ExecutionContext,
        dependencies: Mapping[str, StepResult],
    ) -> StepResult:
        """执行单一步骤，不得理解用户原文或读取未声明依赖。"""


class PlanExecutor:
    """按计划顺序执行步骤，并在首个失败或待输入状态后立即停止。"""

    def __init__(self, adapters: Mapping[str, StepAdapter]) -> None:
        """接收按操作类型注册的适配器；缺失适配器属于稳定执行错误。"""
        self._adapters = dict(adapters)

    async def execute(
        self,
        plan: PlanDecision,
        context: ExecutionContext,
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

        logger.info(
            "[EXECUTOR] 计划开始: plan_id=%s step_count=%s available_config_refs=%s "
            "has_logs=%s available_field_count=%s enum_target_field_count=%s",
            plan.plan_id,
            len(plan.steps),
            list(context.session_facts.available_config_refs),
            context.session_facts.has_logs,
            len(context.session_facts.available_fields),
            len(context.session_facts.enum_mapping_target_fields),
        )
        ledger: dict[str, StepResult] = {}
        ordered_results: list[StepResult] = []
        for step in plan.steps:
            await context.progress_sink.publish(
                ProgressEvent(
                    plan_id=plan.plan_id,
                    step_id=step.step_id,
                    phase=ProgressPhase.EXECUTION,
                    status=ProgressStatus.RUNNING,
                    message_code=f"{step.type}_started",
                )
            )
            logger.info(
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
            preflight_error = self._validate_step(step, context.session_facts, ledger)
            if preflight_error is not None:
                ordered_results.append(preflight_error)
                await self._publish_step_terminal(
                    plan.plan_id,
                    step,
                    preflight_error,
                    context.progress_sink,
                )
                logger.info(
                    "[EXECUTOR] 执行前拦截: plan_id=%s step_id=%s operation=%s status=%s "
                    "error_category=%s required_config_ref=%s observed_config_refs=%s "
                    "has_logs=%s available_field_count=%s enum_target_field_count=%s",
                    plan.plan_id,
                    step.step_id,
                    step.type,
                    preflight_error.status.value,
                    preflight_error.error_code,
                    getattr(step, "config_ref", "none"),
                    list(context.session_facts.available_config_refs),
                    context.session_facts.has_logs,
                    len(context.session_facts.available_fields),
                    len(context.session_facts.enum_mapping_target_fields),
                )
                break

            adapter = self._adapters.get(step.type)
            if adapter is None:
                result = self._error_result(step, "adapter_unavailable", "当前操作尚未配置执行适配器")
            else:
                dependencies = {step_id: ledger[step_id] for step_id in step.depends_on}
                try:
                    result = await adapter.execute(step, context, dependencies)
                    result = self._validate_result(step, result)
                except Exception as error:
                    logger.exception(
                        "[EXECUTOR] 步骤异常: plan_id=%s step_id=%s operation=%s error_category=adapter_failed",
                        plan.plan_id,
                        step.step_id,
                        step.type,
                    )
                    result = self._error_result(step, "adapter_failed", "执行适配器发生异常")

            ledger[step.step_id] = result
            ordered_results.append(result)
            await self._publish_step_terminal(
                plan.plan_id,
                step,
                result,
                context.progress_sink,
            )
            logger.info(
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
        logger.info(
            "[EXECUTOR] 计划结束: plan_id=%s status=%s completed_step_count=%s "
            "declared_step_count=%s",
            plan.plan_id,
            execution_report.status.value,
            len(execution_report.results),
            len(plan.steps),
        )
        return execution_report

    @staticmethod
    async def _publish_step_terminal(
        plan_id: str,
        step: StepSpec,
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
                message_code=(
                    f"{step.type}_completed"
                    if is_success
                    else f"{step.type}_{result.status.value}"
                ),
            )
        )

    def _validate_step(
        self,
        step: StepSpec,
        session_facts: SessionFacts,
        ledger: Mapping[str, StepResult],
    ) -> StepResult | None:
        """集中执行 session 语义和依赖校验，避免各适配器重复解释状态。"""
        for dependency_id in step.depends_on:
            dependency = ledger.get(dependency_id)
            if dependency is None:
                return self._error_result(step, "dependency_missing", "声明的步骤依赖不存在")
            if dependency.status != StepStatus.SUCCESS:
                return self._error_result(step, "dependency_failed", "声明的步骤依赖未成功")

        if isinstance(step, LogParseStep) and not session_facts.has_logs:
            return self._needs_input_result(step, "logs_required", "请先上传包含日志的数据")
        if isinstance(step, FieldMappingStep) and not session_facts.available_fields:
            return self._needs_input_result(step, "fields_required", "请先上传包含可映射字段的数据")
        if (
            isinstance(step, ExportStep)
            and step.source_ref in {"session.decoded_config", "session.mapped_sub_rules"}
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
        return None

    def _validate_result(self, step: StepSpec, result: StepResult) -> StepResult:
        """验证适配器结果属于当前步骤，并阻止填充零变更被静默报告成功。"""
        if result.step_id != step.step_id or result.operation_type != step.type:
            return self._error_result(step, "invalid_step_result", "适配器返回了不匹配的步骤结果")
        if isinstance(step, FillStep) and result.status == StepStatus.SUCCESS and result.changed_count == 0:
            return self._error_result(step, "no_effect", "填充未改变任何目标字段")
        return result

    @staticmethod
    def _error_result(step: StepSpec, error_code: str, message: str) -> StepResult:
        """构造稳定失败结果，不携带敏感输入原值。"""
        return StepResult(
            step_id=step.step_id,
            operation_type=step.type,
            status=StepStatus.FAILED,
            error_code=error_code,
            message=message,
        )

    @staticmethod
    def _needs_input_result(step: StepSpec, error_code: str, message: str) -> StepResult:
        """构造待输入结果，使调用层明确追问而不是猜测参数。"""
        return StepResult(
            step_id=step.step_id,
            operation_type=step.type,
            status=StepStatus.NEEDS_INPUT,
            error_code=error_code,
            message=message,
        )
