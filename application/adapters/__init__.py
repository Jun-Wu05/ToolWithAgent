"""Application StepAdapter 的惰性公共导出，避免适配器间初始化耦合。"""

from __future__ import annotations

from typing import Any

__all__ = [
    "ExportAdapter",
    "EnumExtractAdapter",
    "EnumFillAdapter",
    "FillAdapter",
    "FieldMappingAdapter",
    "FieldMappingBatchError",
    "FieldMappingBatchRunner",
    "FieldMappingExecutionPolicy",
    "LogParseAdapter",
    "ThreatFillAdapter",
    "ThreatMappingAdapter",
]


def __getattr__(name: str) -> Any:
    """按需载入适配器，保留既有 ``application.adapters`` 导入路径。"""
    if name == "ExportAdapter":
        from application.adapters.export import ExportAdapter
        return ExportAdapter
    if name == "EnumExtractAdapter":
        from application.adapters.enum_extract import EnumExtractAdapter
        return EnumExtractAdapter
    if name == "EnumFillAdapter":
        from application.adapters.enum_fill import EnumFillAdapter
        return EnumFillAdapter
    if name == "FillAdapter":
        from application.adapters.fill import FillAdapter
        return FillAdapter
    if name == "FieldMappingAdapter":
        from application.adapters.field_mapping import FieldMappingAdapter
        return FieldMappingAdapter
    if name in {
        "FieldMappingBatchError",
        "FieldMappingBatchRunner",
        "FieldMappingExecutionPolicy",
    }:
        from application import field_mapping_batch
        return getattr(field_mapping_batch, name)
    if name == "LogParseAdapter":
        from application.adapters.log_parse import LogParseAdapter
        return LogParseAdapter
    if name == "ThreatFillAdapter":
        from application.adapters.threat_fill import ThreatFillAdapter
        return ThreatFillAdapter
    if name == "ThreatMappingAdapter":
        from application.adapters.threat_mapping import ThreatMappingAdapter
        return ThreatMappingAdapter
    raise AttributeError(name)
