"""通过类型化来源导出当前配置或日志分类规则。"""

from collections.abc import Mapping

from application.adapters.shared import (
    _CONFIG_SESSION_KEYS,
    _build_config_artifact,
    _failed,
    _is_enum_config_stale,
    _needs_input,
    _read_config,
    require_rule_source_fields,
)
from application.execution import ExecutionContext
from contracts.planner_models import (
    ConfigExportArtifact,
    ExportStep,
    StepResult,
    StepSpec,
    StepStatus,
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
            from agent.tools import rule_generator

            if (
                step.source_ref == "session.log_classification.sub_rules"
                and context.session.mapped_sub_rules
            ):
                return _needs_input(
                    step,
                    "mapped_sub_rules_present",
                    "当前已存在包含字段映射、事件标注和手动调整的完整子规则；"
                    "请使用「生成映射后子规则」导出，避免下载会丢失这些内容的白板版本",
                )
            classification = context.session.log_classification
            if not isinstance(classification, dict) or not classification:
                return _needs_input(step, "log_classification_required", "请先完成日志类型提取")
            rule_source_fields, blocked = require_rule_source_fields(
                context.session, step
            )
            if blocked is not None:
                return blocked
            export_mode = (
                "entry"
                if step.source_ref == "session.log_classification.entry_rules"
                else "sub"
            )
            generated_rules = rule_generator.generate_rules(
                classification,
                mode=export_mode,
                rule_source_fields=rule_source_fields,
            )
            if not generated_rules.get("success"):
                return _failed(step, "rule_export_failed", "规则生成失败")
            rules = generated_rules.get("rules", [])
            exported_text = rule_generator.rules_to_base64_text(rules)
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
