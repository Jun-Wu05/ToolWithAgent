"""Normalize 条目构建模块。

提供子规则 normalize 列表的构建函数，支持 JSON 与 KV 两种日志格式。
包含单条目构建器（key:value / original_log / 日志类型）以及
完整的 normalize 列表构建器（解析 real_samples 或聚合所有日志）。
"""

import json
from typing import Any

from .utils import value_to_str, extract_kv_keys


# ---------------------------------------------------------------------------
# 单条目构建器
# ---------------------------------------------------------------------------

def make_kv_normalize_entry(index: str, value: Any) -> dict[str, Any]:
    """构建一条 key:value normalize 条目（field/sim/entity 均为 null）。"""
    return {
        "mappings": [],
        "field": None,
        "sim": None,
        "result": [value_to_str(value)],
        "info": None,
        "entity": None,
        "required": False,
        "core": None,
        "value": None,
        "index": index,
    }


def make_original_log_entry(raw_text: str) -> dict[str, Any]:
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


def make_log_type_entry(logtype: str) -> dict[str, Any]:
    """构建日志类型 normalize 条目（syslog+JSON / KV 子规则独有）。"""
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


def make_log_type_normalize_entry(logtypes: list[str]) -> dict[str, Any]:
    """构建日志类型 normalize 条目（纯 KV 入口规则使用）。

    result 为空数组，表示不提供样本值。

    Args:
        logtypes: 日志类型列表（未使用，保留参数以保持接口一致性）

    Returns:
        normalize 条目字典
    """
    return {
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
    }


# ---------------------------------------------------------------------------
# Normalize 列表构建器
# ---------------------------------------------------------------------------

def build_json_normalize_entries(
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
            entries.append(make_kv_normalize_entry(key, value))
            # 展开第 2 层子字段（仅 1 层嵌套）
            for child_key in sorted(value.keys()):
                child_val = value[child_key]
                entries.append(
                    make_kv_normalize_entry(f"{key}.{child_key}", child_val)
                )
        else:
            # 原始类型 / list
            entries.append(make_kv_normalize_entry(key, value))

    # 插入 original_log（特殊结构，按 index 字母序自然归位）
    entries.append(make_original_log_entry(real_samples_str))

    # 按 index 字母序排列（original_log 自然排在 o 位置，日志类型 排在最后）
    entries.sort(key=lambda e: e["index"])

    # syslog+JSON 追加日志类型（永远最后）
    if is_syslog_json:
        entries.append(make_log_type_entry(logtype))

    return entries


def build_kv_normalize_entries_from_all_logs(
    all_logs_str: str,
    logtype: str = "",
    delimit: str = " ",
    tab: str = "=",
) -> list[dict[str, Any]]:
    """从所有日志中聚合字段（解决样本代表性不足问题）。

    处理流程：
    1. delimit语义化名称转义（"space" → " "）
    2. 按 logtype 过滤日志行（只保留属于当前日志类型的行）
    3. 遍历过滤后的日志行，按delimit分割成key=value对
    4. 构建normalize条目（按字母序，result为空数组）
    5. 追加日志类型条目（永远最后）

    Args:
        all_logs_str: 所有日志字符串（多行KV格式）
        logtype: 日志类型名称（如 "AUDIT"、"IPS"）
        delimit: 字段分隔符（如"space"、";"）
        tab: 键值分隔符（如"="）

    Returns:
        normalize条目列表
    """
    # 按 logtype 过滤日志行：只保留属于当前日志类型的行
    # logtype 通常出现在日志头或 type= 字段里，用子串匹配判断归属
    if logtype and all_logs_str:
        filtered_lines = [line for line in all_logs_str.split('\n') if logtype in line]
        # 如果过滤后没有行（logtype 可能是中文或变体），回退到全部日志
        filtered_logs_str = '\n'.join(filtered_lines) if filtered_lines else all_logs_str
    else:
        filtered_logs_str = all_logs_str

    keys = extract_kv_keys(filtered_logs_str, delimit, tab=tab)

    entries: list[dict[str, Any]] = []
    for key in keys:
        entries.append(make_kv_normalize_entry(key, None))

    # 按字母序排列
    entries.sort(key=lambda e: e["index"])

    # 追加日志类型条目（永远最后）
    entries.append(make_log_type_entry(logtype))

    return entries


def build_kv_normalize_entries(
    real_samples_str: str,
    logtype: str = "",
    delimit: str = " ",
    tab: str = "=",
) -> list[dict[str, Any]]:
    """解析KV格式字符串，只提取key值构建normalize条目。

    处理流程：
    1. delimit语义化名称转义（"space" → " "）
    2. 按delimit分割成key=value对
    3. 对每个对，找第一个tab位置提取key
    4. 构建normalize条目（按字母序，result为空数组）
    5. 追加日志类型条目（永远最后）

    Args:
        real_samples_str: KV格式字符串（如 "user=admin method=ssh"）
        logtype: 日志类型名称
        delimit: 字段分隔符（如"space"、";"）
        tab: 键值分隔符（如"="）

    Returns:
        normalize条目列表
    """
    keys = extract_kv_keys(real_samples_str, delimit, tab=tab)

    entries: list[dict[str, Any]] = []
    for key in keys:
        entries.append(make_kv_normalize_entry(key, None))

    # 按字母序排列
    entries.sort(key=lambda e: e["index"])

    # 追加日志类型条目（永远最后）
    entries.append(make_log_type_entry(logtype))

    return entries