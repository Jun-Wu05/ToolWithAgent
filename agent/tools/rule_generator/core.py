"""核心规则生成模块。

提供入口规则和子规则的生成逻辑，以及统一入口 generate_rules 和
base64 编码 rules_to_base64_text。

重构说明（本次）：
- generate_sub_rule 内部拆分为 4 个职责单一的私有函数
  （命名 / parser 配置 / filter 装配 / normalize 构建），主函数仅做编排。
- generate_entry_rule 中庞大的 if is_json/is_kv 条件树，
  每个分支体提取为独立的 _configure_*_parser 配置函数，
  主函数仅保留格式判定与调度，逻辑链路清晰可见。
- 入口规则 normalize 末尾追加的"日志类型"条目，复用
  normalize.make_log_type_normalize_entry，消除内联重复 dict。
- 所有输出 dict 的 key 插入顺序与原实现逐字段一致，
  以保证 rules_to_base64_text（未使用 sort_keys）的 base64 输出不变。
"""

import base64
import json
import time
from typing import Any

from contracts.rule_source import RuleSourceFields

from .templates import get_empty_rule_template, get_sub_rule_template
from .utils import now_ms, new_uuid, escape_delimit
from .filters import (
    make_addfields_filter,
    make_redirect_filter,
    make_condition_match_filter,
    make_logtype_mapping_filter,
    make_kv_condition_match_filter,
    make_syslog_kv_condition_match_filter,
)
from .normalize import (
    build_json_normalize_entries,
    build_kv_normalize_entries_from_all_logs,
    build_kv_normalize_entries,
    make_log_type_normalize_entry,
)


# ---------------------------------------------------------------------------
# 公共填充
# ---------------------------------------------------------------------------

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
        uuid_str = new_uuid()
    ts = now_ms()
    rule["id"] = uuid_str
    rule["name"] = name
    rule["description"] = description
    rule["sample"] = sample
    rule["createtime"] = ts
    rule["lasttime"] = ts


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


# ---------------------------------------------------------------------------
# 入口规则：各格式的 parser 配置（从 generate_entry_rule 条件树中提取）
# ---------------------------------------------------------------------------

def _configure_syslog_json_parser(rule: dict[str, Any], logtypes: list[str]) -> None:
    """配置 syslog+JSON 入口规则的 parser。"""
    rule["parser"]["name"] = "orgRegex"
    rule["parser"]["value"] = r"(\{[\S\s]*\})"
    rule["parser"]["filter"] = [
        make_addfields_filter(),
        make_condition_match_filter(logtypes),
    ]


def _configure_pure_json_parser(
    rule: dict[str, Any], logtypes: list[str], feature_field: str
) -> None:
    """配置纯 JSON 入口规则的 parser。"""
    rule["parser"]["name"] = "json"
    # JSON 格式不需要 parser.value，删除模板中的默认值
    rule["parser"].pop("value", None)
    rule["parser"]["filter"] = [
        make_addfields_filter(),
        make_condition_match_filter(logtypes),
        make_logtype_mapping_filter(feature_field),
    ]


def _configure_pure_kv_parser(
    rule: dict[str, Any],
    logtypes: list[str],
    feature_field: str,
    analysis: dict[str, Any],
) -> None:
    """配置纯 KV 入口规则的 parser。"""
    tab = analysis.get("tab", "=")
    delimit = escape_delimit(analysis.get("delimit", " "))

    rule["parser"]["name"] = "delimitWithKeyMap"
    rule["parser"]["tab"] = tab
    rule["parser"]["delimit"] = delimit
    rule["parser"]["filter"] = [
        make_addfields_filter(),
        make_logtype_mapping_filter(feature_field),
        make_kv_condition_match_filter(logtypes, feature_field),
    ]


def _configure_syslog_kv_parser(
    rule: dict[str, Any], logtypes: list[str], classification: dict[str, Any]
) -> None:
    """配置 syslog+KV 入口规则的 parser。"""
    rule["parser"]["name"] = "orgRegex"
    rule["parser"]["value"] = classification.get("feature_identifier", "")
    rule["parser"]["filter"] = [
        make_addfields_filter(),
        make_syslog_kv_condition_match_filter(logtypes),
    ]


def _configure_default_parser(
    rule: dict[str, Any], logtypes: list[str], classification: dict[str, Any]
) -> None:
    """配置默认格式（非 JSON 且非 KV）入口规则的 parser。"""
    rule["parser"]["name"] = "orgRegex"
    rule["parser"]["value"] = classification.get("feature_identifier", "")
    rule["parser"]["filter"] = [
        make_addfields_filter(),
        make_redirect_filter(logtypes),
    ]


# ---------------------------------------------------------------------------
# 入口规则：主生成函数
# ---------------------------------------------------------------------------

def generate_entry_rule(
    classification: dict[str, Any],
    date_str: str = "",
    uuid_str: str = "",
    rule_source_fields: RuleSourceFields | None = None,
) -> dict[str, Any]:
    """生成一条入口规则。

    Args:
        classification: 日志解析输出的完整 JSON（dict）。
        date_str: YYYYMMDD 日期字符串，默认取当天。
        uuid_str: 可复用 UUID，默认自动生成。
    """
    resolved_date = date_str or time.strftime("%Y%m%d")
    rule_name = (
        f"{rule_source_fields.log_vendor}_{rule_source_fields.product}_通用_"
        f"入口规则{resolved_date[-4:]}"
        if rule_source_fields
        else f"入口规则_{resolved_date}"
    )
    details: list[dict[str, Any]] = classification.get(
        "classification_details", []
    )
    logtypes: list[str] = [d.get("logtype", "") for d in details]
    samples: list[str] = [d.get("sample", "") for d in details]

    # 深拷贝模板
    rule: dict[str, Any] = get_empty_rule_template()

    # 填充 id/name/description/sample/createtime/lasttime
    _fill_rule_common(
        rule,
        name=rule_name,
        description=rule_name,
        sample="#next#".join(samples),
        date_str=date_str,
        uuid_str=uuid_str,
    )

    # 根据 log_format 判断入口规则的 parser 配置（分支优先级与原实现一致）
    log_format = (classification.get("log_format", "") or "").upper()
    format_detail = (classification.get("log_format_detail", "") or "")
    is_json = "JSON" in log_format
    is_kv = "KV" in log_format
    is_syslog_json = is_json and ("日志头" in format_detail)
    is_syslog_kv = is_kv and ("日志头" in format_detail)
    is_pure_kv = is_kv and not is_syslog_kv

    feature_field = classification.get("feature_field", "")
    analysis = classification.get("analysis", {})

    if is_json:
        if is_syslog_json:
            _configure_syslog_json_parser(rule, logtypes)
        else:
            _configure_pure_json_parser(rule, logtypes, feature_field)
    elif is_pure_kv:
        _configure_pure_kv_parser(rule, logtypes, feature_field, analysis)
    elif is_syslog_kv:
        _configure_syslog_kv_parser(rule, logtypes, classification)
    else:
        _configure_default_parser(rule, logtypes, classification)

    if rule_source_fields:
        from .source_fields import make_source_fields_filter

        rule["parser"]["filter"].append(make_source_fields_filter(rule_source_fields))

    rule["parser"]["subResolver"] = 0

    # properties
    rule["properties"] = _make_properties(logtypes, rule_name)
    if rule_source_fields:
        from .source_fields import make_source_properties

        rule["properties"].extend(make_source_properties(rule_source_fields))

    # normalize — 保持空规则模板的结构，替换 original_log 的 result
    for norm in rule.get("normalize", []):
        if norm.get("index") == "original_log":
            norm["result"] = samples

    # 纯 JSON 或纯 KV 格式新增日志类型映射 normalize 条目
    # syslog+JSON 和 syslog+KV 不需要（已在子规则中处理）
    # CHANGED: 复用 normalize.make_log_type_normalize_entry，消除内联重复 dict
    if (is_json and not is_syslog_json) or is_pure_kv:
        rule["normalize"].append(make_log_type_normalize_entry(logtypes))

    if rule_source_fields:
        from .source_fields import make_source_normalize_entries

        rule["normalize"].extend(make_source_normalize_entries(rule_source_fields))

    return rule


# ---------------------------------------------------------------------------
# 子规则：职责拆分后的私有函数
# ---------------------------------------------------------------------------

def _build_sub_rule_name(
    logtype: str,
    Diversion_method: str,
    is_json: bool,
    is_kv: bool,
    feature_field: str,
    rule_source_fields: RuleSourceFields | None = None,
) -> str:
    """根据日志格式构建子规则名称。"""
    if rule_source_fields:
        prefix = f"{rule_source_fields.log_vendor}_{rule_source_fields.product}_{logtype}"
        if is_json:
            return f"{prefix}_json_子规则"
        if is_kv:
            return f"{prefix}_kv_子规则"
        return f"{prefix}_{Diversion_method}_子规则"
    if is_json:
        return f"{logtype}_{feature_field}_json_子规则"
    if is_kv:
        return f"{logtype}_kv_子规则"
    return f"{logtype}_{Diversion_method}_子规则"


def _apply_sub_parser_config(
    rule: dict[str, Any],
    parser_name: str,
    analysis: dict[str, Any],
) -> None:
    """根据 parser_name 设置子规则的 parser 附加配置（tab/delimit/fields）。

    JSON parser 无附加配置；delimitWithKeyMap 需要 tab/delimit（转义）；
    delimit 需要 delimit/fields。
    """
    if parser_name == "json":
        pass  # JSON parser 不需要 tab/delimit/fields
    elif parser_name == "delimitWithKeyMap":
        rule["parser"]["tab"] = analysis.get("tab", ":")
        rule["parser"]["delimit"] = escape_delimit(analysis.get("delimit", ";"))
    elif parser_name == "delimit":
        rule["parser"]["delimit"] = analysis.get("delimit", "")
        # delimit 类型的 parser 可能需要 fields 数组
        rule["parser"]["fields"] = []


def _build_sub_rule_filters(
    rule: dict[str, Any],
    is_syslog_json: bool,
    is_kv: bool,
    logtype: str,
) -> None:
    """为 syslog+JSON 或 KV 格式子规则在 filter 中追加日志类型 addFields。"""
    if is_syslog_json or is_kv:
        rule["parser"]["filter"].append({
            "fields": {"日志类型": logtype},
            "name": "addFields",
            "id": "",
        })


def _build_sub_rule_normalize(
    sample: str,
    logtype: str,
    is_json: bool,
    is_kv: bool,
    is_syslog_json: bool,
    all_logs_str: str,
    analysis: dict[str, Any],
) -> list[dict[str, Any]]:
    """根据日志格式构建子规则的 normalize 条目列表。

    JSON 格式通过 build_json_normalize_entries 构建；
    KV 格式通过 build_kv_normalize_entries（或聚合所有日志版本）构建；
    其他格式返回空列表。
    """
    if is_json:
        return build_json_normalize_entries(
            real_samples_str=sample,
            logtype=logtype,
            is_syslog_json=is_syslog_json,
        )
    if is_kv:
        # 如果提供了完整日志字符串，使用聚合字段逻辑
        if all_logs_str:
            return build_kv_normalize_entries_from_all_logs(
                all_logs_str=all_logs_str,
                logtype=logtype,
                delimit=analysis.get("delimit", " "),
                tab=analysis.get("tab", "="),
            )
        # 兜底：使用单条样本逻辑
        return build_kv_normalize_entries(
            real_samples_str=sample,
            logtype=logtype,
            delimit=analysis.get("delimit", " "),
            tab=analysis.get("tab", "="),
        )
    # 其他格式 normalize 保持空
    return []


# ---------------------------------------------------------------------------
# 子规则：主生成函数
# ---------------------------------------------------------------------------

def generate_sub_rule(
    classification_detail: dict[str, Any],
    Diversion_method: str,
    analysis: dict[str, Any],
    all_logs_str: str = "",
    date_str: str = "",
    uuid_str: str = "",
    *,
    is_json: bool = False,
    is_syslog_json: bool = False,
    is_kv: bool = False,
    feature_field: str = "",
    rule_source_fields: RuleSourceFields | None = None,
) -> dict[str, Any]:
    """为单条 classification_detail 生成一条子规则。

    Args:
        classification_detail: classification_details 数组中的单个元素。
        Diversion_method: 分类依据字段名（如 "日志类型"）。
        analysis: classification 顶层的 analysis 对象。
        all_logs_str: 完整日志字符串（用于KV格式聚合字段，解决样本代表性不足）。
        date_str: YYYYMMDD 日期字符串。
        uuid_str: 可复用 UUID。
        is_json: 是否为 JSON 格式（纯JSON 或 syslog+JSON）。
        is_syslog_json: 是否为 syslog+JSON 格式。
        is_kv: 是否为 KV 格式（纯KV 或 syslog+KV）。
        feature_field: 特征字段名（如 "categoryName"、"type"）。
    """
    logtype = classification_detail.get("logtype", "")

    # 职责 1：命名
    rule_name = _build_sub_rule_name(
        logtype, Diversion_method, is_json, is_kv, feature_field, rule_source_fields
    )

    # matched_regex 已废弃，改用 real_samples（fill_sample_logs 输出）或 sample 兜底
    sample = classification_detail.get("real_samples") or classification_detail.get("sample", "")

    # 职责 2：parser 名称
    if is_json:
        parser_name = "json"
    else:
        parser_name = _resolve_sub_parser_name(analysis)

    rule: dict[str, Any] = get_sub_rule_template()

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

    # 职责 2（续）：parser 附加配置
    _apply_sub_parser_config(rule, parser_name, analysis)

    # 职责 3：filter 装配
    _build_sub_rule_filters(rule, is_syslog_json, is_kv, logtype)

    # 职责 4：normalize 构建
    rule["normalize"] = _build_sub_rule_normalize(
        sample=sample,
        logtype=logtype,
        is_json=is_json,
        is_kv=is_kv,
        is_syslog_json=is_syslog_json,
        all_logs_str=all_logs_str,
        analysis=analysis,
    )

    # properties 暂时留空
    rule["properties"] = []

    return rule


def generate_sub_rules(
    classification: dict[str, Any],
    all_logs_str: str = "",
    date_str: str = "",
    rule_source_fields: RuleSourceFields | None = None,
) -> list[dict[str, Any]]:
    """遍历 classification_details 生成所有子规则列表。

    Args:
        classification: 日志解析输出的完整 JSON（dict）。
        all_logs_str: 完整日志字符串（用于KV格式聚合字段，解决样本代表性不足）。
        date_str: YYYYMMDD 日期字符串。

    Returns:
        子规则列表。
    """
    Diversion_method = classification.get("Diversion_method", "")
    analysis = classification.get("analysis", {})
    details: list[dict[str, Any]] = classification.get(
        "classification_details", []
    )

    # 提取 format 标记，传递给 generate_sub_rule 做格式特定处理
    log_format = (classification.get("log_format", "") or "").upper()
    is_json = "JSON" in log_format
    is_kv = "KV" in log_format
    format_detail = (classification.get("log_format_detail", "") or "")
    is_syslog_json = is_json and ("日志头" in format_detail)
    feature_field = classification.get("feature_field", "")

    rules: list[dict[str, Any]] = []
    for detail in details:
        rule = generate_sub_rule(
            classification_detail=detail,
            Diversion_method=Diversion_method,
            analysis=analysis,
            all_logs_str=all_logs_str,
            date_str=date_str,
            is_json=is_json,
            is_syslog_json=is_syslog_json,
            is_kv=is_kv,
            feature_field=feature_field,
            rule_source_fields=rule_source_fields,
        )
        rules.append(rule)
    return rules


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------

def generate_rules(
    classification: dict[str, Any],
    mode: str,
    rule_source_fields: RuleSourceFields | None = None,
) -> dict[str, Any]:
    """根据 mode 生成规则，返回统一的 dict 结构。

    Args:
        classification: 日志解析输出的完整 JSON（dict）。
        mode: "entry" | "sub"

    Returns:
        {"success": bool, "rule_count": int, "rules": list[dict],
         "error": str}
    """
    date_str = time.strftime("%Y%m%d")
    rules: list[dict[str, Any]] = []

    try:
        if mode == "entry":
            rule = generate_entry_rule(
                classification,
                date_str=date_str,
                rule_source_fields=rule_source_fields,
            )
            rules.append(rule)

        if mode == "sub":
            sub_rules = generate_sub_rules(
                classification,
                date_str=date_str,
                rule_source_fields=rule_source_fields,
            )
            rules.extend(sub_rules)

        return {
            "success": True,
            "rule_count": len(rules),
            "rules": rules,
            "error": "",
        }
    except Exception as e:
        return {
            "success": False,
            "rule_count": 0,
            "rules": [],
            "error": str(e),
        }


def rules_to_base64_text(rules_list: list[dict[str, Any]]) -> str:
    """将规则 JSON 数组编码为 base64 字符串（供导出 .txt）。"""
    json_str = json.dumps(rules_list, ensure_ascii=False)
    return base64.b64encode(json_str.encode("utf-8")).decode("ascii")
