"""兼容垫片：历史调用方仍从 web.execution_adapters 导入（Issue #88 拆分后）。

真实实现归属于 Application Adapters 与少量尚未迁移的 Web Adapters；
新代码请直接使用 ``web.adapters.create_default_adapters`` 组合入口。
"""

from web.adapters import create_default_adapters
from web.adapters.agent_ops import ProfessionalAgentAdapter
from web.adapters.config_ops import EnumFillAdapter, RemoveMappingAdapter
from application.adapters.fill import FillAdapter
from application.adapters.threat_fill import ThreatFillAdapter
from application.adapters.threat_mapping import ThreatMappingAdapter
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
