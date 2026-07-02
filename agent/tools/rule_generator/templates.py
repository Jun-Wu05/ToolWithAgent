"""规则模板模块。

提供入口规则和子规则的骨架模板。模板作为模块级常量保存，
通过 ``get_empty_rule_template`` / ``get_sub_rule_template`` 访问器返回深拷贝，
避免全局变量被调用方污染。

注意：模板中的 ``deviceType`` 等业务字段保持原值（如 "1"），
配置外置（读取 空规则.txt）属于后续独立议题，不在本次重构范围内。
"""

import copy
from typing import Any

# ---------------------------------------------------------------------------
# 空规则模板（入口规则骨架，从 config/空规则.txt 精简而来）
# ---------------------------------------------------------------------------

_EMPTY_RULE_TEMPLATE: dict[str, Any] = {
    "name": "",
    "sysType": 0,
    "createtime": 0,
    "source": 0,
    "entities": ["日志"],
    "description": "",
    "normalize": [
        {
            "mappings": [],
            "field": "original_log",
            "sim": True,
            "result": [],
            "info": None,
            "entity": "日志",
            "required": False,
            "core": None,
            "value": None,
            "index": "original_log",
        }
    ],
    "lasttime": 0,
    "parser": {
        "name": "nothing",
        "resolverType": "event",
        "unmappingKeep": False,
        "deviceType": "1",
        "filter": None,
        "subResolver": 0,
    },
    "resolverType": "event",
    "deviceType": {"id": "1", "name": "设备分类", "parentId": ""},
    "simEntities": ["日志", "事件"],
    "version": "v1",
    "change": 0,
    "id": "",
    "properties": [],
    "parserV2": None,
    "sample": "",
    "subResolver": 0,
    "deleted": 0,
}

# 子规则模板（parser.subResolver=1，无 redirect filter）
_SUB_RULE_TEMPLATE: dict[str, Any] = {
    "name": "",
    "sysType": 0,
    "createtime": 0,
    "source": 0,
    "entities": ["日志"],
    "description": "",
    "normalize": [],
    "lasttime": 0,
    "parser": {
        "name": "nothing",
        "resolverType": "event",
        "unmappingKeep": False,
        "deviceType": "1",
        "filter": [
            {
                "fields": {
                    "product": "",
                    "event_name": "",
                    "event_level": "",
                    "log_vendor": "",
                },
                "name": "addFields",
                "id": "additional_fields_filter",
            }
        ],
        "subResolver": 1,
    },
    "resolverType": "event",
    "deviceType": {"id": "1", "name": "设备分类", "parentId": ""},
    "simEntities": ["日志", "事件"],
    "version": "v1",
    "change": 0,
    "id": "",
    "properties": [],
    "parserV2": None,
    "sample": "",
    "subResolver": 1,
    "deleted": 0,
}


def get_empty_rule_template() -> dict[str, Any]:
    """返回入口规则模板的深拷贝。

    CHANGED: 使用 ``copy.deepcopy`` 替代原 ``json.loads(json.dumps())``，
    行为等价但更符合 Python 惯例，性能略优。
    """
    return copy.deepcopy(_EMPTY_RULE_TEMPLATE)


def get_sub_rule_template() -> dict[str, Any]:
    """返回子规则模板的深拷贝。

    CHANGED: 使用 ``copy.deepcopy`` 替代原 ``json.loads(json.dumps())``。
    """
    return copy.deepcopy(_SUB_RULE_TEMPLATE)