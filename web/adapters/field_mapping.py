"""兼容入口：字段映射适配器实现已迁入 Application。"""

from application.adapters.field_mapping import (
    FieldMappingAdapter,
    FieldMappingBatchError,
    FieldMappingExecutionPolicy,
)

__all__ = [
    "FieldMappingAdapter",
    "FieldMappingBatchError",
    "FieldMappingExecutionPolicy",
]
