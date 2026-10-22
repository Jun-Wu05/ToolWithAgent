"""枚举填充适配器：精确替换枚举贡献并更新配置有效性。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agent.shared.logger import get_logger
from agent.shared.mapping_utils import (
    apply_enum_fill_with_contributions,
    count_field_mapping_changes,
    count_field_mappings,
    iter_normalize_entries,
    remove_enum_fill_contributions,
)
from application.adapters.fill_shared import unbind_fixed_field_bindings
from application.adapters.shared import (
    _build_config_artifact,
    _enum_mapping_table,
    _failed,
    _needs_input,
    _read_config,
    _write_config,
)
from application.execution import ExecutionContext
from contracts.planner_models import FillStep, StepResult, StepSpec, StepStatus


logger = get_logger("execution_adapters")


def _find_unmatched_target_fields(
    config: Any, target_fields: tuple[str, ...]
) -> list[str]:
    """返回配置中无任何 index/field 同名条目的映射表目标字段（#402 逐字段严格校验）。"""
    matched: set[str] = set()
    targets = {str(name).strip() for name in target_fields}
    for _path, _position, _owner, entry in iter_normalize_entries(config, require_index=False):
        index_value = str(entry.get("index", "")).strip()
        field_value = str(entry.get("field", "")).strip()
        matched.update({index_value, field_value} & targets)
    return sorted(targets - matched)


class EnumFillAdapter:
    """以显式目标字段和配置来源执行枚举填充及贡献账本更新。"""

    async def execute(
        self,
        step: StepSpec,
        context: ExecutionContext,
        dependencies: Mapping[str, StepResult],
    ) -> StepResult:
        """执行枚举填充，来源缺失时快速失败且不跨配置兜底。"""
        if not isinstance(step, FillStep) or step.fill_kind != "enum":
            raise TypeError("EnumFillAdapter 只接受 enum FillStep")
        current_config = _read_config(context.session, step.config_ref)
        current_config, unbind_note = unbind_fixed_field_bindings(
            current_config, step.target_fields
        )
        enum_preview = context.session.enum_preview or []
        mapping_table = _enum_mapping_table(enum_preview, step.target_fields)
        if not mapping_table:
            return _needs_input(
                step, "enum_mapping_required", "当前枚举映射表没有可用于目标字段的规则"
            )
        # 逐字段严格守卫（#402）：任一映射表目标字段在配置中不存在同名字段时
        # 稳定失败并列出缺失字段，一行不写；不静默丢弃、不部分填充
        # （20261022 混合场景回归：命中字段照写、缺失字段静默丢弃的假成功）。
        unmatched = _find_unmatched_target_fields(current_config, tuple(mapping_table))
        if unmatched:
            return _failed(
                step,
                "enum_target_field_mismatch",
                f"枚举映射表的目标字段（{'、'.join(unmatched)}）在当前配置中不存在，"
                "请检查 Sheet 名与要填充的字段名是否一致，或先在解析规则中补充该字段",
            )
        all_contributions = dict(context.session.enum_fill_contributions or {})
        config_contributions = dict(all_contributions.get(step.config_ref, {}) or {})
        before_count = count_field_mappings(current_config, step.target_fields)
        without_old_contributions = remove_enum_fill_contributions(
            current_config, config_contributions, step.target_fields
        )
        updated_config, new_contributions = apply_enum_fill_with_contributions(
            without_old_contributions, mapping_table
        )
        after_count = count_field_mappings(updated_config, step.target_fields)
        changed_count = count_field_mapping_changes(
            current_config, updated_config, step.target_fields
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
        context.session.enum_fill_contributions = all_contributions
        pending_refills = {
            config_ref: set(sheet_names)
            for config_ref, sheet_names in (
                context.session.enum_pending_refills or {}
            ).items()
        }
        pending_for_config = pending_refills.get(step.config_ref, set())
        pending_for_config.difference_update(step.target_fields)
        if pending_for_config:
            pending_refills[step.config_ref] = pending_for_config
        else:
            pending_refills.pop(step.config_ref, None)
        context.session.enum_pending_refills = pending_refills
        stale_refs = set(context.session.stale_enum_config_refs or set())
        if step.config_ref not in pending_refills:
            stale_refs.discard(step.config_ref)
        context.session.stale_enum_config_refs = stale_refs
        per_field_notes = _build_per_field_notes(mapping_table, new_contributions)
        idempotent = changed_count == 0
        headline = (
            "枚举映射已全部存在，无新增"
            if idempotent
            else "枚举映射已填充到目标字段"
        )
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
            artifact=_build_config_artifact(updated_config, after_count, "enummapping_config"),
            message="；".join(part for part in (headline, per_field_notes) if part)
            + unbind_note,
            idempotent_no_change=idempotent,
        )


def _build_per_field_notes(
    mapping_table: dict[str, list[dict]],
    new_contributions: dict[str, list[dict[str, Any]]],
) -> str:
    """逐字段汇总新增与已存在计数（#402），全部字段零新增时返回空串。"""
    notes: list[str] = []
    for field_name, rows in mapping_table.items():
        added = len(new_contributions.get(field_name) or [])
        existing = len(rows) - added
        if added:
            notes.append(f"{field_name}：新增 {added} 条；已存在 {existing} 条")
        elif existing:
            notes.append(f"{field_name}：{existing} 条映射已全部存在，无新增")
    return "；".join(notes)


__all__ = ["EnumFillAdapter"]
