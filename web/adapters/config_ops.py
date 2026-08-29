"""填充、取消映射与导出适配器（Issue #88 拆分自 execution_adapters）。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agent.shared.logger import get_logger
from agent.shared.mapping_utils import count_field_mappings, remove_field_mappings_from_config
from application.adapters.export import ExportAdapter
from application.adapters.fill import FillAdapter
from application.adapters.threat_fill import ThreatFillAdapter
from application.adapters.enum_fill import EnumFillAdapter

from application.execution import ExecutionContext
from contracts.planner_models import (
    RemoveMappingStep,
    StepResult,
    StepSpec,
    StepStatus,
)
from application.adapters.shared import (
    _build_config_artifact,
    _failed,
    _is_enum_config_stale,
    _needs_input,
    _read_config,
    _write_config,
    format_field_vocabulary,
    resolve_field_names,
)


logger = get_logger("execution_adapters")
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
        # 目标字段名解析（#146）：标准名唯一映射到原始 index 后再取消映射
        resolved_targets, resolution_problems = resolve_field_names(
            current_config, list(step.target_fields)
        )
        if resolution_problems:
            problem = resolution_problems[0]
            if problem["kind"] == "ambiguous":
                return _failed(
                    step,
                    "field_name_ambiguous",
                    (
                        f"字段「{problem['name']}」是标准字段名，对应多个原始字段："
                        f"{'、'.join(problem['candidates'])}；请改用其中的原始字段名"
                    ),
                )
            return _failed(
                step,
                "field_not_found",
                (
                    f"未找到字段「{problem['name']}」。"
                    f"可用字段（原始名(标准名)）："
                    f"{format_field_vocabulary(current_config)}"
                ),
            )
        effective_targets = tuple(
            resolved_targets[name] for name in step.target_fields
        )
        resolution_changes = {
            name: resolved_targets[name]
            for name in step.target_fields
            if resolved_targets[name] != name
        }
        before_count = count_field_mappings(current_config, effective_targets)
        updated_config = current_config
        for target_field in effective_targets:
            updated_config = remove_field_mappings_from_config(updated_config, target_field)
        after_count = count_field_mappings(updated_config, effective_targets)
        if before_count == after_count:
            return _needs_input(step, "mapping_not_found", "目标字段没有可取消的映射")
        _write_config(context.session, step.config_ref, updated_config)
        note = (
            f"；字段解析：{'、'.join(f'{k}→{v}' for k, v in resolution_changes.items())}"
            if resolution_changes
            else ""
        )
        logger.info(
            "[REMOVE_MAPPING] 取消完成: step_id=%s config_ref=%s target_field_count=%s "
            "before_count=%s after_count=%s changed_count=%s",
            step.step_id,
            step.config_ref,
            len(effective_targets),
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
            message="目标字段映射已取消" + note,
        )
