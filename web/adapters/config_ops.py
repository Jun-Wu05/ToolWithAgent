"""填充、取消映射与导出适配器（Issue #88 拆分自 execution_adapters）。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agent.shared.logger import get_logger
from agent.shared.mapping_utils import (
    apply_enum_fill_with_contributions,
    apply_fill_to_config,
    count_field_mapping_changes,
    count_field_mappings,
    remove_enum_fill_contributions,
    remove_field_mappings_from_config,
    unbind_fixed_fields,
)
from agent.tools.rule_generator.field_mapping import MAPPING_EXCLUDED_STANDARD_FIELDS
from contracts.artifact_targets import collect_standard_fields, resolve_standard_target

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
from contracts.session_artifacts import ThreatArtifactSlot
from web.adapters.shared import (
    _CONFIG_SESSION_KEYS,
    _build_config_artifact,
    _enum_mapping_table,
    _failed,
    _is_enum_config_stale,
    _needs_input,
    _read_config,
    _session_get,
    _session_set,
    _write_config,
)


logger = get_logger("execution_adapters")


def _unbind_fixed_field_bindings(
    config: Any, target_fields: tuple[str, ...]
) -> tuple[Any, str]:
    """填充即解绑（#126）：固定字段的绑定固定值会让值映射失效，先解除。"""
    fixed_hit = set(target_fields) & MAPPING_EXCLUDED_STANDARD_FIELDS
    if not fixed_hit:
        return config, ""
    updated, unbound = unbind_fixed_fields(config, target_fields)
    if not unbound:
        return config, ""
    note = (
        f"；已解除 {len(unbound)} 条规则的固定值绑定"
        f"（{'、'.join(sorted(fixed_hit))} 改由值映射控制）"
    )
    logger.info(
        "[FILL_UNBIND] 填充即解绑: target_fields=%s unbound_rules=%s",
        sorted(fixed_hit),
        len(unbound),
    )
    return updated, note


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
        current_config, unbind_note = _unbind_fixed_field_bindings(
            current_config, step.target_fields
        )
        enum_preview = _session_get(context.session, "enum_preview") or []
        mapping_table = _enum_mapping_table(enum_preview, step.target_fields)
        if not mapping_table:
            return _needs_input(step, "enum_mapping_required", "当前枚举映射表没有可用于目标字段的规则")

        all_contributions = dict(
            _session_get(context.session, "enum_fill_contributions", {}) or {}
        )
        config_contributions = dict(all_contributions.get(step.config_ref, {}) or {})
        before_count = count_field_mappings(current_config, step.target_fields)
        without_old_contributions = remove_enum_fill_contributions(
            current_config,
            config_contributions,
            step.target_fields,
        )
        updated_config, new_contributions = apply_enum_fill_with_contributions(
            without_old_contributions,
            mapping_table,
        )
        after_count = count_field_mappings(updated_config, step.target_fields)
        changed_count = count_field_mapping_changes(
            current_config,
            updated_config,
            step.target_fields,
        )
        _write_config(context.session, step.config_ref, updated_config)
        for field_name in step.target_fields:
            if new_contributions.get(field_name):
                config_contributions[field_name] = new_contributions[field_name]
            else:
                config_contributions.pop(field_name, None)
        if config_contributions:
            all_contributions[step.config_ref] = config_contributions
        else:
            all_contributions.pop(step.config_ref, None)
        _session_set(context.session, "enum_fill_contributions", all_contributions)
        pending_refills = {
            config_ref: set(sheet_names)
            for config_ref, sheet_names in (
                _session_get(context.session, "enum_pending_refills", {}) or {}
            ).items()
        }
        pending_for_config = pending_refills.get(step.config_ref, set())
        pending_for_config.difference_update(step.target_fields)
        if pending_for_config:
            pending_refills[step.config_ref] = pending_for_config
        else:
            pending_refills.pop(step.config_ref, None)
        _session_set(context.session, "enum_pending_refills", pending_refills)
        stale_refs = set(
            _session_get(context.session, "stale_enum_config_refs", set()) or set()
        )
        if step.config_ref not in pending_refills:
            stale_refs.discard(step.config_ref)
        _session_set(context.session, "stale_enum_config_refs", stale_refs)
        logger.info(
            "[ENUM_FILL] 填充完成: step_id=%s config_ref=%s target_field_count=%s "
            "mapping_rule_count=%s before_count=%s after_count=%s changed_count=%s",
            step.step_id,
            step.config_ref,
            len(step.target_fields),
            sum(len(items) for items in mapping_table.values()),
            before_count,
            after_count,
            changed_count,
        )
        return StepResult(
            step_id=step.step_id,
            operation_type=step.type,
            status=StepStatus.SUCCESS,
            changed_count=changed_count,
            artifact=_build_config_artifact(
                updated_config,
                after_count,
                "enummapping_config",
            ),
            message="枚举映射已填充到目标字段" + unbind_note,
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
        if _is_enum_config_stale(context.session, step.config_ref):
            return _needs_input(
                step,
                "enum_refill_required",
                "枚举映射附件已更新，请先重新执行枚举填充",
            )
        if step.source_ref == "session.artifacts.threat_mapping":
            raw_slot = _session_get(context.session, "latest_threat_artifact")
            try:
                slot = (
                    raw_slot
                    if isinstance(raw_slot, ThreatArtifactSlot)
                    else ThreatArtifactSlot.model_validate(raw_slot)
                )
            except (TypeError, ValueError):
                return _needs_input(
                    step,
                    "artifact_source_unavailable",
                    "最近威胁映射产物已不可用，请重新执行威胁映射",
                )
            artifact = slot.artifact
            current_config = _read_config(context.session, step.config_ref)
            if artifact.source_field:
                expected_target = resolve_standard_target(current_config, artifact.source_field)
                if expected_target is None:
                    return _needs_input(
                        step,
                        "artifact_target_unavailable",
                        "最近威胁映射的来源字段没有唯一可填充标准字段",
                    )
                if step.target_fields != (expected_target,):
                    return _needs_input(
                        step,
                        "artifact_target_mismatch",
                        f"最近威胁映射只能填回标准字段: {expected_target}",
                    )
            else:
                available_targets = set(collect_standard_fields(current_config))
                if step.target_fields[0] not in available_targets:
                    return _needs_input(
                        step,
                        "artifact_target_unavailable",
                        "指定字段不是当前配置中的可填充标准字段",
                    )
        else:
            dependency_id = step.source_ref.removeprefix("step:")
            dependency = dependencies.get(dependency_id)
            if dependency is None or dependency.artifact is None:
                return _failed(step, "dependency_missing", "威胁填充缺少声明的映射产物")
            if not isinstance(dependency.artifact, ThreatMappingArtifact):
                return _failed(step, "dependency_type_mismatch", "依赖产物不是威胁映射")
            artifact = dependency.artifact

        current_config = _read_config(context.session, step.config_ref)
        current_config, unbind_note = _unbind_fixed_field_bindings(
            current_config, step.target_fields
        )

        mapping_rows = [row.model_dump(by_alias=True) for row in artifact.mappings]
        if not mapping_rows:
            return _failed(step, "threat_mapping_empty", "威胁映射产物为空")

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
            artifact=_build_config_artifact(
                updated_config,
                after_count,
                "threatmapping_config",
            ),
            message="威胁映射已填充到目标字段" + unbind_note,
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
        if _is_enum_config_stale(context.session, step.config_ref):
            return _needs_input(
                step,
                "enum_refill_required",
                "枚举映射附件已更新，请先重新执行枚举填充",
            )
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
            artifact=_build_config_artifact(
                updated_config,
                after_count,
                "cancelmapping_config",
            ),
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
            download_kind = artifact.download_kind
        elif step.source_ref in _CONFIG_SESSION_KEYS:
            if _is_enum_config_stale(context.session, step.source_ref):
                return _needs_input(
                    step,
                    "enum_refill_required",
                    "枚举映射附件已更新，请先重新执行枚举填充",
                )
            current_config = _read_config(context.session, step.source_ref)
            if not current_config:
                return _needs_input(step, "export_source_required", "当前没有可导出的配置")
            exported_item_count = len(current_config) if isinstance(current_config, list) else 1
            exported_text = _build_config_artifact(current_config, exported_item_count).content
            download_kind = (
                "mappedconfig_subrules"
                if step.source_ref == "session.mapped_sub_rules"
                else "current_config"
            )
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
            download_kind = (
                "mappedconfig_mainrules"
                if step.source_ref == "session.log_classification.entry_rules"
                else "unmappedconfig_subrules"
            )

        return StepResult(
            step_id=step.step_id,
            operation_type=step.type,
            status=StepStatus.SUCCESS,
            artifact=ConfigExportArtifact(
                content=exported_text,
                item_count=exported_item_count,
                download_kind=download_kind,
            ),
            message="配置已导出",
        )
