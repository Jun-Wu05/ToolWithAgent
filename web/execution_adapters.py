"""兼容垫片：历史调用方仍从 web.execution_adapters 导入（Issue #88 拆分后）。

真实实现位于 web/adapters/ 三档模块；新代码请直接使用
``web.adapters.create_default_adapters``。
"""

from web.adapters import create_default_adapters
from web.adapters.agent_ops import ProfessionalAgentAdapter
from web.adapters.config_ops import (
    EnumFillAdapter,
    FillAdapter,
    RemoveMappingAdapter,
    ThreatFillAdapter,
)
from application.adapters.export import ExportAdapter
from web.adapters.field_mapping import (
    FieldMappingAdapter,
    FieldMappingBatchError,
    FieldMappingExecutionPolicy,
)
from application.adapters.shared import logger

__all__ = [
    "create_default_adapters",
    "ProfessionalAgentAdapter",
    "FieldMappingAdapter",
    "FieldMappingBatchError",
    "FieldMappingExecutionPolicy",
    "EnumFillAdapter",
    "ThreatFillAdapter",
    "FillAdapter",
    "RemoveMappingAdapter",
    "ExportAdapter",
    "logger",
]
