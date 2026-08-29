"""生产 StepAdapter 的唯一组合入口。

落位：
- Application Adapters —— field_mapping / log_parse / enum_extract / enum_fill / export
- agent_ops.py —— threat_mapping 与迁移期专业 Agent 委托
- config_ops.py —— threat fill / remove_mapping 与枚举填充兼容导出
- skill_ops.py —— add_fields / delete_fields / merge_fields 字段调整（PRD #124）

``create_default_adapters`` 是唯一公共组合入口，PlanExecutor 按 ``step.type``
字符串键注册分派，不感知适配器内部结构。
"""

from typing import Any

from application.adapters.export import ExportAdapter
from application.adapters.enum_extract import EnumExtractAdapter
from application.adapters.enum_fill import EnumFillAdapter
from application.adapters.field_mapping import (
    FieldMappingAdapter,
    FieldMappingBatchError,
    FieldMappingExecutionPolicy,
)
from application.adapters.log_parse import LogParseAdapter
from application.execution import StepAdapter
from web.adapters.agent_ops import ProfessionalAgentAdapter
from web.adapters.config_ops import (
    FillAdapter,
    RemoveMappingAdapter,
    ThreatFillAdapter,
)
from web.adapters.skill_ops import FieldSkillAdapter, FIELD_SKILL_REGISTRY


def create_default_adapters(team: Any) -> dict[str, StepAdapter]:
    """创建统一执行器的默认适配器表，操作类型是唯一分派键。"""
    professional_adapter = ProfessionalAgentAdapter(team)
    log_parse_adapter = LogParseAdapter()
    field_mapping_adapter = FieldMappingAdapter(team)
    field_skill_adapter = FieldSkillAdapter()
    return {
        "log_parse": log_parse_adapter,
        "field_mapping": field_mapping_adapter,
        "enum_extract": EnumExtractAdapter(),
        "threat_mapping": professional_adapter,
        "fill": FillAdapter(),
        "remove_mapping": RemoveMappingAdapter(),
        "export": ExportAdapter(),
        **{step_type: field_skill_adapter for step_type in FIELD_SKILL_REGISTRY},
    }
