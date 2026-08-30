"""兼容垫片：历史调用方仍从 web.execution_adapters 导入（Issue #88 拆分后）。

真实实现归属于 Application Adapters 与少量迁移期 Web 兼容委托；
新代码请直接使用 Application 组合入口。
"""

from application.adapters.composition import create_default_adapters
from web.adapters.agent_ops import ProfessionalAgentAdapter
from application.adapters.enum_fill import EnumFillAdapter
from application.adapters.fill import FillAdapter
from application.adapters.threat_fill import ThreatFillAdapter
from application.adapters.threat_mapping import ThreatMappingAdapter
from application.adapters.remove_mapping import RemoveMappingAdapter
from application.adapters.export import ExportAdapter
from application.adapters.field_mapping import (
    FieldMappingAdapter,
    FieldMappingBatchError,
    FieldMappingExecutionPolicy,
)
from application.adapters.log_parse import LogParseAdapter
from application.adapters.shared import logger

__all__ = [
    "create_default_adapters",
    "ProfessionalAgentAdapter",
    "FieldMappingAdapter",
    "FieldMappingBatchError",
    "FieldMappingExecutionPolicy",
    "EnumFillAdapter",
    "ThreatFillAdapter",
    "ThreatMappingAdapter",
    "FillAdapter",
    "RemoveMappingAdapter",
    "ExportAdapter",
    "LogParseAdapter",
    "logger",
]
