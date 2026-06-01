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


def _fill_rule_common(
    rule: dict[str, Any],
    *,
    name: str,
    description: str,
    sample: str,
    date_str: str = "",
    uuid_str: str = "",
) -> None:
    """填充入口/子规则的公共字段（在深拷贝后的 rule dict 上原地修改）。

    统一处理 date_str/uuid_str 默认值、时间戳、id/name/description/sample 等字段，
    消除 generate_entry_rule 和 generate_sub_rule 的重复代码。
    """
    if not date_str:
        date_str = time.strftime("%Y%m%d")
    if not uuid_str:
        uuid_str = _new_uuid()
    ts = _now_ms()
    rule["id"] = uuid_str
    rule["name"] = name
    rule["description"] = description
    rule["sample"] = sample
    rule["createtime"] = ts
    rule["lasttime"] = ts


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
    """构建入口规则的 redirect filter（cases 覆盖所有 logtype）— KV/syslog 格式使用。"""
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


def _make_condition_match_filter(logtypes: list[str]) -> dict[str, Any]:
    """构建纯 JSON 入口规则的 conditionMatch filter。

    每个 case 的 value 格式固定为 ``original_log like '{logtype}'``，
    用于匹配包含特定 logtype 的 JSON 日志行。
    """
    cases: list[dict[str, Any]] = []
    for lt in logtypes:
        cases.append(
            {
                "value": f"original_log like '{lt}'",
                "rule": {"fields": {"1": "1"}, "name": "addFields", "id": ""},
                "name": "case",
                "id": "",
            }
        )
    return {
        "cases": cases,
        "default": {"name": "none"},
        "name": "conditionMatch",
        "id": "",
    }


def _make_feature_field_filter(feature_field: str) -> dict[str, Any]:
    """构建纯 JSON 入口规则的第三个 filter（将 feature_field 映射为日志类型）。

    key 恒为 ``日志类型``，value 格式固定为 ``%{feature_field}``。
    """
    return {
        "fields": {"日志类型": f"%{{{feature_field}}}"},
        "name": "addFields",
        "id": "",
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


def _resolve_sub_parser_name(analysis: dict[str, Any]) -> str:
    """根据 analysis 判断子规则 parser.name。

    Returns:
        "delimitWithKeyMap" / "delimit" / "orgRegex"
    """
    # 🔮 预留扩展：未来可增加 cef / xml / csv 等格式的 parser 类型判断
    if analysis.get("has_key_value_pairs"):
        return "delimitWithKeyMap"
    if analysis.get("has_delimited_structure"):
        return "delimit"
    return "orgRegex"


def _value_to_str(value: Any) -> str:
    """将 JSON 值转为 normalize result 所需的字符串形式。

    - None → ""；bool → "true"/"false"（小写 JSON 风格）
    - int / float → str(value)；str → 原值
    - dict / list → json.dumps（ensure_ascii=False, sort_keys=True）
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value
    # dict / list → JSON 字符串
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _make_kv_normalize_entry(index: str, value: Any) -> dict[str, Any]:
    """构建一条 key:value normalize 条目（field/sim/entity 均为 null）。"""
    return {
        "mappings": [],
        "field": None,
        "sim": None,
        "result": [_value_to_str(value)],
        "info": None,
        "entity": None,
        "required": False,
        "core": None,
        "value": None,
        "index": index,
    }


def _make_original_log_entry(raw_text: str) -> dict[str, Any]:
    """构建 original_log normalize 条目（field/sim/entity 有特殊值）。"""
    return {
        "mappings": [],
        "field": "original_log",
        "sim": True,
        "result": [raw_text],
        "info": None,
        "entity": "日志",
        "required": False,
        "core": False,
        "value": None,
        "index": "original_log",
    }


def _make_log_type_entry(logtype: str) -> dict[str, Any]:
    """构建日志类型 normalize 条目（syslog+JSON 子规则独有）。"""
    return {
        "mappings": [],
        "field": "log_type",
        "sim": True,
        "result": [logtype],
        "info": None,
        "entity": "日志",
        "required": False,
        "core": False,
        "value": "",
        "index": "日志类型",
    }


def _build_json_normalize_entries(
    real_samples_str: str,
    logtype: str = "",
    is_syslog_json: bool = False,
) -> list[dict[str, Any]]:
    """解析 real_samples JSON，构建子规则的完整 normalize 条目列表。

    处理流程：
    1. json.loads 解析 real_samples
    2. 遍历第 1 层 key（字母序）：
       - 原始类型 → {index: key, result: [str(value)]}
       - dict 值 → 父级 JSON 字符串 + 展开第 2 层子字段 (parent.child)
       - list 值 → JSON 字符串
    3. 插入 original_log entry（按字母序自然归位）
    4. 如果 is_syslog_json，追加日志类型 entry（永远最后）

    Args:
        real_samples_str: real_samples JSON 字符串。
        logtype: 当前子规则的日志类型名称。
        is_syslog_json: 是否为 syslog+JSON 格式。

    Raises:
        json.JSONDecodeError: real_samples 不是合法 JSON 时直接抛出。
    """
    data: dict[str, Any] = json.loads(real_samples_str)
    entries: list[dict[str, Any]] = []

    for key in sorted(data.keys()):
        value = data[key]

        if isinstance(value, dict):
            # 父级 entry：JSON 字符串（sort_keys 保持一致性）
            entries.append(_make_kv_normalize_entry(key, value))
            # 展开第 2 层子字段（仅 1 层嵌套）
            for child_key in sorted(value.keys()):
                child_val = value[child_key]
                entries.append(
                    _make_kv_normalize_entry(f"{key}.{child_key}", child_val)
                )
        else:
            # 原始类型 / list
            entries.append(_make_kv_normalize_entry(key, value))

    # 插入 original_log（特殊结构，按 index 字母序自然归位）
    entries.append(_make_original_log_entry(real_samples_str))

    # 按 index 字母序排列（original_log 自然排在 o 位置，日志类型 排在最后）
    entries.sort(key=lambda e: e["index"])

    # syslog+JSON 追加日志类型（永远最后）
    if is_syslog_json:
        entries.append(_make_log_type_entry(logtype))

    return entries


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
    rule_name = f"入口规则_{date_str or time.strftime('%Y%m%d')}"
    details: list[dict[str, Any]] = classification.get(
        "classification_details", []
    )
    logtypes: list[str] = [d.get("logtype", "") for d in details]
    samples: list[str] = [d.get("sample", "") for d in details]

    # 深拷贝模板
    rule: dict[str, Any] = json.loads(json.dumps(_EMPTY_RULE_TEMPLATE))

    # CHANGED: 使用公共函数填充 id/name/description/sample/createtime/lasttime
    _fill_rule_common(
        rule,
        name=rule_name,
        description=rule_name,
        sample="#next#".join(samples),
        date_str=date_str,
        uuid_str=uuid_str,
    )

    # CHANGED: 根据 log_format 判断入口规则的 parser 配置
    log_format = (classification.get("log_format", "") or "").upper()
    is_json = "JSON" in log_format

    if is_json:
        format_detail = (classification.get("log_format_detail", "") or "")
        is_syslog_json = "日志头" in format_detail

        if is_syslog_json:
            # syslog+JSON 格式入口规则
            rule["parser"]["name"] = "orgRegex"
            rule["parser"]["value"] = r"(\{[\S\s]*\})"
            rule["parser"]["filter"] = [
                _make_addfields_filter(),
                _make_condition_match_filter(logtypes),
            ]
        else:
            # 纯 JSON 格式入口规则
            feature_field = classification.get("feature_field", "")
            rule["parser"]["name"] = "json"
            # JSON 格式不需要 parser.value，删除模板中的默认值
            rule["parser"].pop("value", None)
            rule["parser"]["filter"] = [
                _make_addfields_filter(),
                _make_condition_match_filter(logtypes),
                _make_feature_field_filter(feature_field),
            ]
    else:
        # 🔮 预留扩展：KV / syslog / 分隔符格式入口规则（原有逻辑）
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

    # CHANGED: 纯 JSON 格式新增日志类型映射 normalize 条目（syslog+JSON 不需要）
    if is_json and not is_syslog_json:
        rule["normalize"].append({
            "mappings": [],
            "field": "log_type",
            "sim": True,
            "result": [],
            "info": None,
            "entity": "日志",
            "required": False,
            "core": False,
            "value": "",
            "index": "日志类型",
        })

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
    *,
    is_json: bool = False,
    is_syslog_json: bool = False,
    is_pure_json: bool = False,
    feature_field: str = "",
) -> dict[str, Any]:
    """为单条 classification_detail 生成一条子规则。

    Args:
        classification_detail: classification_details 数组中的单个元素。
        Diversion_method: 分类依据字段名（如 "日志类型"）。
        analysis: classification 顶层的 analysis 对象。
        date_str: YYYYMMDD 日期字符串。
        uuid_str: 可复用 UUID。
        is_json: 是否为 JSON 格式（纯JSON 或 syslog+JSON）。
        is_syslog_json: 是否为 syslog+JSON 格式。
        is_pure_json: 是否为纯 JSON 格式。
        feature_field: 特征字段名（如 "categoryName"、"type"）。
    """
    logtype = classification_detail.get("logtype", "")

    # CHANGED: JSON 格式子规则 name 用 feature_field + "json"，非 JSON 用 Diversion_method
    if is_json:
        rule_name = f"{logtype}_{feature_field}_json_子规则"
    else:
        rule_name = f"{logtype}_{Diversion_method}_子规则"

    # CHANGED: matched_regex 已废弃，改用 real_samples（fill_sample_logs 输出）或 sample 兜底
    sample = classification_detail.get("real_samples") or classification_detail.get("sample", "")

    # CHANGED: JSON 格式子规则 parser.name 恒为 "json"
    if is_json:
        parser_name = "json"
    else:
        parser_name = _resolve_sub_parser_name(analysis)

    rule: dict[str, Any] = json.loads(json.dumps(_SUB_RULE_TEMPLATE))

    # CHANGED: 使用公共函数填充 id/name/description/sample/createtime/lasttime
    _fill_rule_common(
        rule,
        name=rule_name,
        description=rule_name,
        sample=sample,
        date_str=date_str,
        uuid_str=uuid_str,
    )
    rule["subResolver"] = 1
    rule["parser"]["name"] = parser_name
    rule["parser"]["subResolver"] = 1

    # CHANGED: JSON parser 无附加配置；delimitWithKeyMap 需要 tab/delimit，delimit 需要 delimit/fields
    if parser_name == "json":
        pass  # JSON parser 不需要 tab/delimit/fields
    elif parser_name == "delimitWithKeyMap":
        rule["parser"]["tab"] = analysis.get("tab", ":")
        rule["parser"]["delimit"] = analysis.get("delimit", ";")
    elif parser_name == "delimit":
        rule["parser"]["delimit"] = analysis.get("delimit", "")
        # delimit 类型的 parser 可能需要 fields 数组
        rule["parser"]["fields"] = []

    # CHANGED: syslog+JSON 子规则在 filter 中追加日志类型 addFields
    if is_syslog_json:
        rule["parser"]["filter"].append({
            "fields": {"日志类型": logtype},
            "name": "addFields",
            "id": "",
        })

    # CHANGED: JSON 格式子规则通过 _build_json_normalize_entries 构建完整 normalize
    # KV/syslog 格式 normalize 保持空
    if is_json:
        rule["normalize"] = _build_json_normalize_entries(
            real_samples_str=sample,
            logtype=logtype,
            is_syslog_json=is_syslog_json,
        )
    else:
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

    # CHANGED: 提取 format 标记，传递给 generate_sub_rule 做格式特定处理
    log_format = (classification.get("log_format", "") or "").upper()
    is_json = "JSON" in log_format
    format_detail = (classification.get("log_format_detail", "") or "")
    is_syslog_json = is_json and ("日志头" in format_detail)
    is_pure_json = is_json and not is_syslog_json
    feature_field = classification.get("feature_field", "")

    rules: list[dict[str, Any]] = []
    for detail in details:
        rule = generate_sub_rule(
            classification_detail=detail,
            Diversion_method=Diversion_method,
            analysis=analysis,
            date_str=date_str,
            is_json=is_json,
            is_syslog_json=is_syslog_json,
            is_pure_json=is_pure_json,
            feature_field=feature_field,
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