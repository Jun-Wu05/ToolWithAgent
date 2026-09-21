"""全部 Application StepAdapter 的唯一生产组合根。"""

from __future__ import annotations

from typing import Any

from application.adapters.enum_extract import EnumExtractAdapter
from application.adapters.export import ExportAdapter
from application.adapters.field_mapping import FieldMappingAdapter
from application.adapters.field_skill import FIELD_SKILL_REGISTRY, FieldSkillAdapter
from application.adapters.fill import FillAdapter
from application.adapters.log_parse import LogParseAdapter
from application.adapters.log_knowledge_submit import LogKnowledgeSubmitAdapter
from application.adapters.remove_mapping import RemoveMappingAdapter
from application.adapters.threat_mapping import ThreatMappingAdapter
from application.execution import StepAdapter


def create_default_adapters(team: Any) -> dict[str, StepAdapter]:
    """创建以 StepSpec 类型为键的完整生产分派表。"""
    field_skill_adapter = FieldSkillAdapter()
    return {
        "log_parse": LogParseAdapter(),
        "log_knowledge_submit": LogKnowledgeSubmitAdapter(),
        "field_mapping": FieldMappingAdapter(team),
        "enum_extract": EnumExtractAdapter(),
        "threat_mapping": ThreatMappingAdapter(team),
        "fill": FillAdapter(),
        "remove_mapping": RemoveMappingAdapter(),
        "export": ExportAdapter(),
        **{step_type: field_skill_adapter for step_type in FIELD_SKILL_REGISTRY},
    }
