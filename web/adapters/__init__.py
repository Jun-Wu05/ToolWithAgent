"""Compatibility exports for the Application Adapter composition root.

落位：
- Application Adapters —— field_mapping / log_parse / enum / threat / fill / export
- agent_ops.py —— 迁移期专业 Agent 兼容委托
- config_ops.py —— 配置操作的迁移期同对象兼容导出
- Application Adapters —— 字段 Skills 调整运行时（PRD #124 / Issue #140）

New production callers import ``application.adapters.composition`` directly.
"""

from application.adapters.composition import create_default_adapters
from application.adapters.export import ExportAdapter
from application.adapters.enum_extract import EnumExtractAdapter
from application.adapters.enum_fill import EnumFillAdapter
from application.adapters.field_mapping import (
    FieldMappingAdapter,
    FieldMappingBatchError,
    FieldMappingExecutionPolicy,
)
from application.adapters.field_skill import FieldSkillAdapter, FIELD_SKILL_REGISTRY
from application.adapters.log_parse import LogParseAdapter
from application.adapters.remove_mapping import RemoveMappingAdapter
from application.adapters.fill import FillAdapter
from application.adapters.threat_fill import ThreatFillAdapter
from application.adapters.threat_mapping import ThreatMappingAdapter
from web.adapters.agent_ops import ProfessionalAgentAdapter
