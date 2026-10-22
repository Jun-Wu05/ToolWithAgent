"""威胁类型映射 Application StepAdapter。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from agent.core.standard_field_catalog import get_standard_field_catalog
from agent.shared.logger import get_logger
from application.adapters.shared import (
    _failed,
    _needs_input,
    _success,
    run_member_stream,
)
from application.execution import (
    ExecutionContext,
    threat_mapping_source_precondition,
)
from application.parsing import parse_json_threat_result
from application.threat_chain_policy import (
    DEGRADED_THREAT_VALUE,
    is_code_only_value,
    validate_threat_mapping_coverage,
)
from contracts.planner_models import (
    THREAT_TYPE_FIELD,
    EnumValuesArtifact,
    StepResult,
    StepSpec,
    ThreatMappingArtifact,
    ThreatMappingRow,
    ThreatMappingStep,
)
from contracts.session_artifacts import ThreatArtifactSlot

logger = get_logger("execution_adapters")


def _standard_threat_targets() -> set[str]:
    """解析威胁类型标准枚举集合；数据源为 config/标准字段.txt（单一事实源）。"""
    field = get_standard_field_catalog().lookup(THREAT_TYPE_FIELD)
    if field is None or not field.enum_values:
        return set()
    return {value.strip() for value in field.enum_values.split(",") if value.strip()}


class ThreatMappingAdapter:
    """从显式枚举来源生成威胁映射并提交可引用会话产物。"""

    def __init__(self, team: Any) -> None:
        self._team = team

    async def execute(
        self,
        step: StepSpec,
        context: ExecutionContext,
        dependencies: Mapping[str, StepResult],
    ) -> StepResult:
        """只消费声明来源，调用一次 ThreatAgent，通过统一覆盖校验后提交双槽。"""
        if not isinstance(step, ThreatMappingStep):
            raise TypeError("ThreatMappingAdapter 只接受 ThreatMappingStep")

        source_field: str | None = None
        if step.source_ref == "user.values":
            values = list(step.values)
        elif step.source_ref == "session.artifacts.enum_values":
            # 前置条件单一来源（#320）：与执行器预检消费同一实现，
            # 直连适配器的调用路径也保持同一拦截语义。
            slot, blocked = threat_mapping_source_precondition(step, context.session)
            if blocked is not None:
                return blocked
            values = list(slot.artifact.values)
            source_field = slot.source_field
        else:
            dependency_id = step.source_ref.removeprefix("step:")
            dependency = dependencies.get(dependency_id)
            artifact = dependency.artifact if dependency else None
            if not isinstance(artifact, EnumValuesArtifact):
                return _failed(step, "dependency_type_mismatch", "依赖产物不是枚举值")
            values = list(artifact.values)
            source_field = artifact.field or None

        # 无语义数字代码（#277）：输入不含任何语义证据时先于模型调用安全
        # 失败，不调用也不采信模型猜测；混合输入不提前拒绝，仍走统一覆盖校验。
        if values and all(is_code_only_value(value) for value in values):
            return _needs_input(
                step,
                "threat_mapping_source_context_required",
                "输入全部为无语义数字代码，无法可靠映射威胁类型；"
                "请改用含语义的来源字段，或提供代码表后重试",
            )

        valid_targets = _standard_threat_targets()
        if not valid_targets:
            return _failed(
                step,
                "threat_mapping_reference_unavailable",
                "威胁类型标准枚举不可用，无法校验映射结果",
            )

        model_input = json.dumps({"values": values}, ensure_ascii=False)
        try:
            content = await run_member_stream(self._team, "ThreatAgent", model_input)
            mapping_rows = parse_json_threat_result(content)
        except Exception as error:
            logger.warning(
                "[THREAT_MAPPING] 模型调用异常: error=%s", type(error).__name__
            )
            if not values:
                return _failed(step, "threat_mapping_empty", "威胁映射未生成有效结果")
            return self._degrade_and_submit(
                step, context, values, source_field, f"模型调用异常 {type(error).__name__}"
            )
        if not mapping_rows:
            if not values:
                return _failed(step, "threat_mapping_empty", "威胁映射未生成有效结果")
            return self._degrade_and_submit(
                step, context, values, source_field, "空结果"
            )
        # 统一来源覆盖校验（#277）：三种声明来源共用同一校验与错误语义；
        # #394 调整：来源外、缺项、重叠或枚举外结果不再整体失败，降级全部
        # 映射行落「其他」并留痕——行级洗白仍禁止，字段级降级显式可见。
        violation = validate_threat_mapping_coverage(values, mapping_rows, valid_targets)
        if violation:
            logger.info(
                "[THREAT_MAPPING] 统一覆盖校验拒绝: rule=%s value_count=%s row_count=%s",
                violation,
                len(values),
                len(mapping_rows),
            )
            return self._degrade_and_submit(
                step, context, values, source_field, f"覆盖校验拒绝 {violation}"
            )

        typed_mappings = tuple(ThreatMappingRow.model_validate(row) for row in mapping_rows)
        artifact = ThreatMappingArtifact(
            mappings=typed_mappings,
            item_count=len(typed_mappings),
            source_field=source_field,
        )
        context.session.last_threat_data = mapping_rows
        context.session.latest_threat_artifact = ThreatArtifactSlot(
            artifact=artifact, source_field=source_field
        )
        return _success(step, artifact)

    def _degrade_and_submit(
        self,
        step: StepSpec,
        context: ExecutionContext,
        values: list[str],
        source_field: str | None,
        reason: str,
    ) -> StepResult:
        """模型终态失败降级：全部映射行落「其他」，步骤成功并留痕（#394）。"""
        rows = [
            {
                "mappingType": "EQUAL",
                "orgValue": value,
                "mappingValue": DEGRADED_THREAT_VALUE,
            }
            for value in values
        ]
        typed_mappings = tuple(ThreatMappingRow.model_validate(row) for row in rows)
        artifact = ThreatMappingArtifact(
            mappings=typed_mappings,
            item_count=len(typed_mappings),
            source_field=source_field,
        )
        context.session.last_threat_data = rows
        context.session.latest_threat_artifact = ThreatArtifactSlot(
            artifact=artifact, source_field=source_field
        )
        logger.warning(
            "[THREAT_MAPPING] 终态失败已降级: reason=%s value_count=%s 全部落「%s」",
            reason,
            len(values),
            DEGRADED_THREAT_VALUE,
        )
        return _success(
            step,
            artifact,
            message=(
                f"威胁映射终态失败（{reason}），已降级全部映射值落「{DEGRADED_THREAT_VALUE}」"
            ),
        )
