"""兼容入口：字段来源实现已迁入 Application。"""

from application.field_source import (
    _extract_kv_fields_from_lines,
    extract_log_body_keys,
    extract_log_fields_for_mapping,
)

__all__ = [
    "_extract_kv_fields_from_lines",
    "extract_log_body_keys",
    "extract_log_fields_for_mapping",
]
