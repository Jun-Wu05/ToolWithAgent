"""规则生成模块：根据日志分类结果生成入口规则和子规则（纯函数，不依赖 Chainlit）。

Typical usage:
    from agent.tools.rule_generator import generate_rules, rules_to_base64_text
    rules = generate_rules(classification, mode="both")
    txt = rules_to_base64_text(rules)
"""

import json
import base64
import uuid
import time
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_ms() -> int:
    """返回当前毫秒级时间戳（int）。"""
    return int(time.time() * 1000)


def _new_uuid() -> str:
    """返回不带连字符的 UUID（小写）。"""
    return str(uuid.uuid4())


def _make_addfields_filter() -> dict[str, Any]:
    """构建 additional_fields_filter 节点。"""
    return {
        "fields": {
            "product": "",
            "event_name": "",
            "event_level": "",
            "log_vendor": "",
        },
        "name": "addFields",
        "id": "additional_fields_filter",
    }


def _make_redirect_filter(logtypes: list[str]) -> dict[str, Any]:
    """构建入口规则的 redirect filter（cases 覆盖所有 logtype）。"""
    cases: list[dict[str, Any]] = []
    for lt in logtypes:
        cases.append(
            {
                "value": lt,
                "rule": {"fields": ["test"], "name": "removeFields", "id": ""},
                "name": "case",
                "id": "",
            }
        )
    return {
        "name": "redirect",
        "field": "1",
        "id": "",
        "default": {"name": "none"},
        "cases": cases,
    }


def _make_properties(
    logtypes: list[str], rule_name: str
) -> list[dict[str, Any]]:
    """构建入口规则的 properties 字段（log_type + rule_name_list）。"""
    return [
        {
            "format": None,
            "name": "日志类型",
            "sim": True,
            "info": [],
            "key": "log_type",
            "entity": "日志",
            "sample": logtypes,
            "type": "object",
            "required": None,
            "core": None,
        },
        {
            "format": None,
            "name": "解析规则链",
            "sim": None,
            "info": [],
            "key": "rule_name_list",
            "entity": None,
            "sample": [f"[{rule_name}]" for _ in logtypes],
            "type": "object",
            "required": None,
            "core": None,
        },
    ]


def _determine_parser_name(analysis: dict[str, Any]) -> str:
    """根据 analysis 判断子规则 parser.name。

    Returns:
        "delimitWithKeyMap" / "delimit" / "orgRegex"
    """
    if analysis.get("has_key_value_pairs"):
        return "delimitWithKeyMap"
    if analysis.get("has_delimited_structure"):
        return "delimit"
    return "orgRegex"


# ---------------------------------------------------------------------------
# 入口规则
# ---------------------------------------------------------------------------

def generate_entry_rule(
    classification: dict[str, Any],
    date_str: str = "",
    uuid_str: str = "",
) -> dict[str, Any]:
    """生成一条入口规则。

    Args:
        classification: 日志解析输出的完整 JSON（dict）。
        date_str: YYYYMMDD 日期字符串，默认取当天。
        uuid_str: 可复用 UUID，默认自动生成。
    """
    if not date_str:
        date_str = time.strftime("%Y%m%d")
    if not uuid_str:
        uuid_str = _new_uuid()

    rule_name = f"入口规则_{date_str}"
    details: list[dict[str, Any]] = classification.get(
        "classification_details", []
    )
    logtypes: list[str] = [d.get("logtype", "") for d in details]
    samples: list[str] = [d.get("sample", "") for d in details]

    ts = _now_ms()

    # 深拷贝模板
    rule: dict[str, Any] = json.loads(json.dumps(_EMPTY_RULE_TEMPLATE))

    rule["id"] = uuid_str
    rule["name"] = rule_name
    rule["description"] = rule_name
    rule["sample"] = "#next#".join(samples)
    rule["createtime"] = ts
    rule["lasttime"] = ts

    # parser
    rule["parser"]["name"] = "orgRegex"
    rule["parser"]["value"] = classification.get("feature_identifier", "")
    rule["parser"]["filter"] = [
        _make_addfields_filter(),
        _make_redirect_filter(logtypes),
    ]
    rule["parser"]["subResolver"] = 0

    # properties
    rule["properties"] = _make_properties(logtypes, rule_name)

    # normalize — 保持空规则模板的结构，替换 original_log 的 result
    for norm in rule.get("normalize", []):
        if norm.get("index") == "original_log":
            norm["result"] = samples

    return rule


# ---------------------------------------------------------------------------
# 子规则
# ---------------------------------------------------------------------------

def generate_sub_rule(
    classification_detail: dict[str, Any],
    Diversion_method: str,
    analysis: dict[str, Any],
    date_str: str = "",
    uuid_str: str = "",
) -> dict[str, Any]:
    """为单条 classification_detail 生成一条子规则。

    Args:
        classification_detail: classification_details 数组中的单个元素。
        Diversion_method: 分类依据字段名（如 "日志类型"）。
        analysis: classification 顶层的 analysis 对象。
        date_str: YYYYMMDD 日期字符串。
        uuid_str: 可复用 UUID。
    """
    if not date_str:
        date_str = time.strftime("%Y%m%d")
    if not uuid_str:
        uuid_str = _new_uuid()

    logtype = classification_detail.get("logtype", "")
    rule_name = f"{logtype}_{Diversion_method}_子规则"
    # CHANGED: matched_regex 已废弃，改用 real_samples（fill_sample_logs 输出）或 sample 兜底
    sample = classification_detail.get("real_samples") or classification_detail.get("sample", "")

    ts = _now_ms()
    parser_name = _determine_parser_name(analysis)

    rule: dict[str, Any] = json.loads(json.dumps(_SUB_RULE_TEMPLATE))
    rule["id"] = uuid_str
    rule["name"] = rule_name
    rule["description"] = rule_name
    rule["sample"] = sample
    rule["createtime"] = ts
    rule["lasttime"] = ts
    rule["subResolver"] = 1
    rule["parser"]["name"] = parser_name
    rule["parser"]["subResolver"] = 1

    # delimitWithKeyMap 需要 tab 字段，delimit 需要 delimit 字段
    if parser_name == "delimitWithKeyMap":
        rule["parser"]["tab"] = analysis.get("tab", ":")
        rule["parser"]["delimit"] = analysis.get("delimit", ";")
    elif parser_name == "delimit":
        rule["parser"]["delimit"] = analysis.get("delimit", "")
        # delimit 类型的 parser 可能需要 fields 数组
        rule["parser"]["fields"] = []

    # normalize 暂时留空（后续通过 build_normalize_fields 完善）
    rule["normalize"] = []

    # properties 暂时留空
    rule["properties"] = []

    return rule


def generate_sub_rules(
    classification: dict[str, Any],
    date_str: str = "",
) -> list[dict[str, Any]]:
    """遍历 classification_details 生成所有子规则列表。"""
    Diversion_method = classification.get("Diversion_method", "")
    analysis = classification.get("analysis", {})
    details: list[dict[str, Any]] = classification.get(
        "classification_details", []
    )

    rules: list[dict[str, Any]] = []
    for detail in details:
        rule = generate_sub_rule(
            classification_detail=detail,
            Diversion_method=Diversion_method,
            analysis=analysis,
            date_str=date_str,
        )
        rules.append(rule)
    return rules


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------

def generate_rules(
    classification: dict[str, Any], mode: str = "both"
) -> dict[str, Any]:
    """根据 mode 生成规则，返回统一的 dict 结构。

    Args:
        classification: 日志解析输出的完整 JSON（dict）。
        mode: "entry" | "sub" | "both"

    Returns:
        {"success": bool, "rule_count": int, "rules": list[dict],
         "file_name": str, "error": str}
    """
    date_str = time.strftime("%Y%m%d")
    rules: list[dict[str, Any]] = []

    try:
        if mode in ("entry", "both"):
            rule = generate_entry_rule(classification, date_str=date_str)
            rules.append(rule)

        if mode in ("sub", "both"):
            sub_rules = generate_sub_rules(classification, date_str=date_str)
            rules.extend(sub_rules)

        # 生成文件名
        feature_field = classification.get("feature_field", "log_type")
        if mode == "entry":
            suffix = f"入口规则_{feature_field}"
        elif mode == "sub":
            suffix = f"子规则_{feature_field}"
        else:
            suffix = f"规则_{feature_field}"
        file_name = f"{suffix}_{date_str}.txt"

        return {
            "success": True,
            "rule_count": len(rules),
            "rules": rules,
            "file_name": file_name,
            "error": "",
        }
    except Exception as e:
        return {
            "success": False,
            "rule_count": 0,
            "rules": [],
            "file_name": "",
            "error": str(e),
        }


def rules_to_base64_text(rules_list: list[dict[str, Any]]) -> str:
    """将规则 JSON 数组编码为 base64 字符串（供导出 .txt）。"""
    json_str = json.dumps(rules_list, ensure_ascii=False)
    return base64.b64encode(json_str.encode("utf-8")).decode("ascii")