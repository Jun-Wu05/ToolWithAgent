"""兼容入口：字段调整 Skills 运行时实现已迁入 Application。"""

from application.adapters.field_skill import (
    FIELD_SKILL_REGISTRY,
    FieldSkillAdapter,
    _load_skill_function,
)

__all__ = [
    "FIELD_SKILL_REGISTRY",
    "FieldSkillAdapter",
    "_load_skill_function",
]
