"""入口规则数据源固定字段的纯结构构建器。"""

from __future__ import annotations

from typing import Any

from contracts.rule_source import RuleSourceFields


_FIELD_SPECS = (
    ("product", "数据源产品", True),
    ("log_vendor", "数据源厂商", True),
    ("data_source", "数据源", False),
)


def make_source_fields_filter(fields: RuleSourceFields) -> dict[str, Any]:
    """构建追加在入口 parser.filter 末尾的固定值绑定。"""
    return {
        "fields": {
            "data_source": fields.data_source,
            "log_vendor": fields.log_vendor,
            "product": fields.product,
        },
        "name": "addFields",
        "id": "",
    }


def make_source_normalize_entries(
    fields: RuleSourceFields,
) -> list[dict[str, Any]]:
    """构建产品、厂商、数据源三条入口 normalize。"""
    return [
        {
            "mappings": [],
            "field": key,
            "sim": False,
            "result": [getattr(fields, key)],
            "info": None,
            "entity": "日志",
            "required": False,
            "core": core,
            "value": None,
            "index": key,
        }
        for key, _name, core in _FIELD_SPECS
    ]


def make_source_properties(fields: RuleSourceFields) -> list[dict[str, Any]]:
    """构建入口规则展示用的三个属性声明。"""
    return [
        {
            "format": None,
            "name": name,
            "sim": False,
            "info": [],
            "key": key,
            "entity": "日志",
            "sample": [getattr(fields, key)],
            "type": "object",
            "required": False,
            "core": core,
        }
        for key, name, core in _FIELD_SPECS
    ]


__all__ = [
    "make_source_fields_filter",
    "make_source_normalize_entries",
    "make_source_properties",
]
