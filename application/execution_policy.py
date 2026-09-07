"""Application 默认执行策略与 PlanExecutor 组合。"""

from __future__ import annotations

from collections.abc import Mapping

from agent.shared.event_classify import EVENT_NAME_FIELD, EVENT_NAME_LEVEL_BINDING
from agent.shared.logger import get_logger
from application.execution import ExecutionContext, PlanExecutor, StepAdapter
from application.field_source import extract_log_body_keys
from contracts.planner_models import (
    AddFieldsStep,
    EnumExtractStep,
    LogParseStep,
    PlanDecision,
    StepResult,
    StepSpec,
    StepStatus,
)

logger = get_logger("plan_executor")


def _failed(step: StepSpec, error_code: str, message: str) -> StepResult:
    """构造稳定的执行前失败结果。"""
    return StepResult(
        step_id=step.step_id,
        operation_type=step.type,
        status=StepStatus.FAILED,
        error_code=error_code,
        message=message,
    )


def _needs_input(step: StepSpec, error_code: str, message: str) -> StepResult:
    """构造稳定的执行前待输入结果。"""
    return StepResult(
        step_id=step.step_id,
        operation_type=step.type,
        status=StepStatus.NEEDS_INPUT,
        error_code=error_code,
        message=message,
    )


class DefaultExecutionPolicy:
    """集中事件名称与显式点名字段的计划级守卫。"""

    def validate_plan(
        self, plan: PlanDecision, context: ExecutionContext
    ) -> tuple[StepSpec, StepResult] | None:
        """非法事件名称必须在任何步骤写入前拦截。"""
        for step in plan.steps:
            if not (
                isinstance(step, AddFieldsStep) and step.field_name == EVENT_NAME_FIELD
            ):
                continue
            if step.value_type == "reference":
                return step, _failed(
                    step,
                    "invalid_event_name",
                    f"{EVENT_NAME_FIELD}必须是固定分类名，不支持引用型值；"
                    "整份计划未执行，当前配置未改动",
                )
            if step.field_value not in EVENT_NAME_LEVEL_BINDING:
                legal = "、".join(EVENT_NAME_LEVEL_BINDING)
                return step, _failed(
                    step,
                    "invalid_event_name",
                    f"{EVENT_NAME_FIELD}必须是以下分类名之一: {legal}；"
                    "整份计划未执行，当前配置未改动",
                )
        return None

    def validate_step(
        self,
        step: StepSpec,
        context: ExecutionContext,
        ledger: Mapping[str, StepResult],
    ) -> StepResult | None:
        """显式点名字段不存在时停下追问，不代用户猜测。"""
        if isinstance(step, EnumExtractStep):
            enum_result = self._validate_enum_target_field(step, context)
            if enum_result is not None:
                return enum_result
        if not (isinstance(step, LogParseStep) and step.feature_field):
            return None
        session = context.session
        log_lines = session.get("raw_log_lines") or session.get("original_log") or []
        if not log_lines:
            return None
        available_keys = extract_log_body_keys(log_lines)
        if step.feature_field in available_keys:
            return None
        case_matches = [
            key for key in available_keys if key.lower() == step.feature_field.lower()
        ]
        if len(case_matches) == 1:
            canonical = case_matches[0]
            logger.info(
                "[FEATURE_FIELD] 大小写不敏感唯一匹配，规范化执行: "
                "step_id=%s feature_field=%s -> %s",
                step.step_id,
                step.feature_field,
                canonical,
            )
            step.feature_field = canonical
            return None
        nearest = case_matches[0] if case_matches else None
        ambiguity = (
            f"（存在多个仅大小写不同的键：{'、'.join(case_matches)}）"
            if case_matches
            else ""
        )
        hint = f"（与「{step.feature_field}」最接近：{nearest}）" if nearest else ""
        return _needs_input(
            step,
            "feature_field_not_found",
            (
                f"日志类型提取未执行：日志中不存在字段「{step.feature_field}」"
                f"{hint}{ambiguity}。"
                f"日志中可用的字段：{'、'.join(available_keys)}。"
                "请回复要作为日志类型的字段名，或直接说“日志类型提取”由系统自动探测。"
            ),
        )

    def _validate_enum_target_field(
        self, step: EnumExtractStep, context: ExecutionContext
    ) -> StepResult | None:
        """枚举目标字段不在日志体键与映射投影的并集时停下追问（#196）。

        放行集取并集而非仅 available_fields：enum 适配器消费原始日志，
        只查映射投影会误拦未映射的原始字段（#66/#70 教训）；并集为空
        视为无词典可校验，放行保持旧行为。大小写差异不改写目标字段
        （链路来源字段逐字契约），只提示最接近字段。
        """
        session = context.session
        log_lines = session.get("raw_log_lines") or session.get("original_log") or []
        known_fields = sorted(
            {*extract_log_body_keys(log_lines), *context.session_facts.available_fields}
        )
        if not known_fields or step.target_field in known_fields:
            return None
        case_matches = [
            field for field in known_fields if field.lower() == step.target_field.lower()
        ]
        hint = (
            f"（与「{step.target_field}」最接近：{case_matches[0]}）" if case_matches else ""
        )
        return _needs_input(
            step,
            "enum_target_field_not_found",
            (
                f"枚举提取未执行：当前会话不存在字段「{step.target_field}」{hint}。"
                f"可用的字段：{'、'.join(known_fields)}。"
                "请回复要提取枚举值的字段名。"
            ),
        )


def create_plan_executor(adapters: Mapping[str, StepAdapter]) -> PlanExecutor:
    """用默认领域守卫组合框架无关执行核心。"""
    return PlanExecutor(adapters, policy=DefaultExecutionPolicy(), logger=logger)
