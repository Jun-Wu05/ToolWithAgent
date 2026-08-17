"""填充、取消映射与导出适配器（Issue #88 拆分自 execution_adapters）。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agent.shared.logger import get_logger
from agent.shared.mapping_utils import (
    apply_fill_to_config,
    count_field_mappings,
    remove_field_mappings_from_config,
)

from web.plan_executor import ExecutionContext
from contracts.planner_models import (
    ConfigExportArtifact,
    ExportStep,
    FillStep,
    RemoveMappingStep,
    StepResult,
    StepSpec,
    StepStatus,
    ThreatMappingArtifact,
)
from web.adapters.shared import (
    _CONFIG_SESSION_KEYS,
    _build_config_artifact,
    _enum_mapping_table,
    _failed,
    _needs_input,
    _read_config,
    _session_get,
    _write_config,
)


logger = get_logger("execution_adapters")


class EnumFillAdapter:
    """以显式目标字段和配置来源执行枚举填充。"""

    async def execute(
        self,
        step: StepSpec,
        context: ExecutionContext,
        dependencies: Mapping[str, StepResult],
    ) -> StepResult:
        """执行枚举填充；任一来源缺失时快速失败且不读取其他配置兜底。"""
        if not isinstance(step, FillStep) or step.fill_kind != "enum":
            raise TypeError("EnumFillAdapter 只接受 enum FillStep")
        current_config = _read_config(context.session, step.config_ref)
        enum_preview = _session_get(context.session, "enum_preview") or []
        mapping_table = _enum_mapping_table(enum_preview, step.target_fields)
        if not mapping_table:
            return _needs_input(step, "enum_mapping_required", "当前枚举映射表没有可用于目标字段的规则")

        before_count = count_field_mappings(current_config, step.target_fields)
        updated_config = apply_fill_to_config(current_config, mapping_table)
        after_count = count_field_mappings(updated_config, step.target_fields)
        _write_config(context.session, step.config_ref, updated_config)
        logger.info(
            "[ENUM_FILL] 填充完成: step_id=%s config_ref=%s target_field_count=%s "
            "mapping_rule_count=%s before_count=%s after_count=%s changed_count=%s",
            step.step_id,
            step.config_ref,
            len(step.target_fields),
            sum(len(items) for items in mapping_table.values()),
            before_count,
            after_count,
            max(0, after_count - before_count),
        )
        return StepResult(
            step_id=step.step_id,
            operation_type=step.type,
            status=StepStatus.SUCCESS,
            changed_count=max(0, after_count - before_count),
            artifact=_build_config_artifact(updated_config, after_count),
            message="枚举映射已填充到目标字段",
        )

class ThreatFillAdapter:
    """只消费本次声明的威胁映射产物并填充显式配置来源。"""

    async def execute(
        self,
        step: StepSpec,
        context: ExecutionContext,
        dependencies: Mapping[str, StepResult],
    ) -> StepResult:
        """执行威胁填充；依赖或配置来源不匹配时快速失败。"""
        if not isinstance(step, FillStep) or step.fill_kind != "threat":
            raise TypeError("ThreatFillAdapter 只接受 threat FillStep")
        dependency_id = step.source_ref.removeprefix("step:")
        dependency = dependencies.get(dependency_id)
        if dependency is None or dependency.artifact is None:
            return _failed(step, "dependency_missing", "威胁填充缺少声明的映射产物")
        if not isinstance(dependency.artifact, ThreatMappingArtifact):
            return _failed(step, "dependency_type_mismatch", "依赖产物不是威胁映射")
        mapping_rows = [row.model_dump(by_alias=True) for row in dependency.artifact.mappings]
        if not mapping_rows:
            return _failed(step, "threat_mapping_empty", "威胁映射产物为空")

        current_config = _read_config(context.session, step.config_ref)
        before_count = count_field_mappings(current_config, step.target_fields)
        updated_config = current_config
        for target_field in step.target_fields:
            updated_config = apply_fill_to_config(updated_config, mapping_rows, target_field)
        after_count = count_field_mappings(updated_config, step.target_fields)
        _write_config(context.session, step.config_ref, updated_config)
        logger.info(
            "[THREAT_FILL] 填充完成: step_id=%s config_ref=%s target_field_count=%s "
            "mapping_rule_count=%s before_count=%s after_count=%s changed_count=%s",
            step.step_id,
            step.config_ref,
            len(step.target_fields),
            len(mapping_rows),
            before_count,
            after_count,
            max(0, after_count - before_count),
        )
        return StepResult(
            step_id=step.step_id,
            operation_type=step.type,
            status=StepStatus.SUCCESS,
            changed_count=max(0, after_count - before_count),
            artifact=_build_config_artifact(updated_config, after_count),
            message="威胁映射已填充到目标字段",
        )

class FillAdapter:
    """按类型化 fill_kind 委派填充实现，不从文本或 session 猜测类型。"""

    def __init__(self) -> None:
        """创建两种明确的填充实现。"""
        self._enum_adapter = EnumFillAdapter()
        self._threat_adapter = ThreatFillAdapter()

    async def execute(
        self,
        step: StepSpec,
        context: ExecutionContext,
        dependencies: Mapping[str, StepResult],
    ) -> StepResult:
        """仅根据 FillStep.fill_kind 分派，未知类型由 Pydantic 在更早阶段拒绝。"""
        if not isinstance(step, FillStep):
            raise TypeError("FillAdapter 只接受 FillStep")
        if step.fill_kind == "enum":
            return await self._enum_adapter.execute(step, context, dependencies)
        return await self._threat_adapter.execute(step, context, dependencies)


class RemoveMappingAdapter:
    """清除显式配置来源中目标字段的 mappings，并导出完整配置。"""

    async def execute(
        self,
        step: StepSpec,
        context: ExecutionContext,
        dependencies: Mapping[str, StepResult],
    ) -> StepResult:
        """执行取消映射；没有实际清除时返回待输入，禁止静默成功。"""
        if not isinstance(step, RemoveMappingStep):
            raise TypeError("RemoveMappingAdapter 只接受 RemoveMappingStep")
        current_config = _read_config(context.session, step.config_ref)
        before_count = count_field_mappings(current_config, step.target_fields)
        updated_config = current_config
        for target_field in step.target_fields:
            updated_config = remove_field_mappings_from_config(updated_config, target_field)
        after_count = count_field_mappings(updated_config, step.target_fields)
        if before_count == after_count:
            return _needs_input(step, "mapping_not_found", "目标字段没有可取消的映射")
        _write_config(context.session, step.config_ref, updated_config)
        logger.info(
            "[REMOVE_MAPPING] 取消完成: step_id=%s config_ref=%s target_field_count=%s "
            "before_count=%s after_count=%s changed_count=%s",
            step.step_id,
            step.config_ref,
            len(step.target_fields),
            before_count,
            after_count,
            before_count - after_count,
        )
        return StepResult(
            step_id=step.step_id,
            operation_type=step.type,
            status=StepStatus.SUCCESS,
            changed_count=before_count - after_count,
            artifact=_build_config_artifact(updated_config, after_count),
            message="目标字段映射已取消",
        )

class ExportAdapter:
    """导出当前明确来源的配置，不改变 session 状态。"""

    async def execute(
        self,
        step: StepSpec,
        context: ExecutionContext,
        dependencies: Mapping[str, StepResult],
    ) -> StepResult:
        """导出 session 领域结果或声明依赖的配置产物。"""
        if not isinstance(step, ExportStep):
            raise TypeError("ExportAdapter 只接受 ExportStep")

        if step.source_ref.startswith("step:"):
            dependency_id = step.source_ref.removeprefix("step:")
            dependency = dependencies.get(dependency_id)
            artifact = dependency.artifact if dependency else None
            if not isinstance(artifact, ConfigExportArtifact):
                return _failed(step, "dependency_type_mismatch", "声明的依赖没有配置产物")
            exported_text = artifact.content
            exported_item_count = artifact.item_count
        elif step.source_ref in _CONFIG_SESSION_KEYS:
            current_config = _read_config(context.session, step.source_ref)
            if not current_config:
                return _needs_input(step, "export_source_required", "当前没有可导出的配置")
            exported_item_count = len(current_config) if isinstance(current_config, list) else 1
            exported_text = _build_config_artifact(current_config, exported_item_count).content
        else:
            from agent.tools.rule_generator import generate_rules, rules_to_base64_text

            classification = _session_get(context.session, "log_classification")
            if not isinstance(classification, dict) or not classification:
                return _needs_input(step, "log_classification_required", "请先完成日志类型提取")
            export_mode = (
                "entry"
                if step.source_ref == "session.log_classification.entry_rules"
                else "sub"
            )
            generated_rules = generate_rules(classification, mode=export_mode)
            if not generated_rules.get("success"):
                return _failed(step, "rule_export_failed", "规则生成失败")
            rules = generated_rules.get("rules", [])
            exported_text = rules_to_base64_text(rules)
            exported_item_count = len(rules)

        return StepResult(
            step_id=step.step_id,
            operation_type=step.type,
            status=StepStatus.SUCCESS,
            artifact=ConfigExportArtifact(
                content=exported_text,
                item_count=exported_item_count,
            ),
            message="配置已导出",
        )
