"""解析可引用会话产物在配置 normalize 中的标准目标字段。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def collect_standard_fields(config: Any) -> tuple[str, ...]:
    """收集配置中非空 normalize.field，去重后稳定排序。"""
    fields: set[str] = set()

    def visit(node: Any) -> None:
        if isinstance(node, Mapping):
            normalize = node.get("normalize")
            if isinstance(normalize, list):
                for item in normalize:
                    if not isinstance(item, Mapping):
                        continue
                    field_value = str(item.get("field", "")).strip()
                    if field_value:
                        fields.add(field_value)
            for child in node.values():
                visit(child)
            return
        if isinstance(node, (list, tuple)):
            for child in node:
                visit(child)

    visit(config)
    return tuple(sorted(fields))


def resolve_standard_target(config: Any, source_field: str) -> str | None:
    """从 normalize.index 到 normalize.field 解析唯一、非空的标准目标字段。"""
    targets: set[str] = set()

    def visit(node: Any) -> None:
        if isinstance(node, Mapping):
            normalize = node.get("normalize")
            if isinstance(normalize, list):
                for item in normalize:
                    if not isinstance(item, Mapping):
                        continue
                    index_value = str(item.get("index", "")).strip()
                    field_value = str(item.get("field", "")).strip()
                    if field_value and (index_value == source_field or field_value == source_field):
                        targets.add(field_value)
            for child in node.values():
                visit(child)
            return
        if isinstance(node, (list, tuple)):
            for child in node:
                visit(child)

    visit(config)
    return next(iter(targets)) if len(targets) == 1 else None
