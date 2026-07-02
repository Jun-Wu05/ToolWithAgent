"""Filter 构建模块。

提供规则中各类 filter（addFields / redirect / conditionMatch）的构建函数。

重构说明（本次）：
- 提取通用 case 构建辅助 ``_make_case``，消除各 conditionMatch/redirect
  函数中重复的 ``{"value": ..., "rule": ..., "name": "case", "id": ""}`` 构造代码。
- 合并完全相同的 ``_make_feature_field_filter`` 与原 ``_make_kv_logtype_filter``
  （二者输出 dict 逐字段一致）为 ``make_logtype_mapping_filter``。
- 各 filter 函数返回的 dict，其 key 插入顺序**严格保持与原实现一致**，
  以保证 ``rules_to_base64_text``（未使用 sort_keys）的 base64 输出不变。
"""

from typing import Any


def _make_case(value: str, rule: dict[str, Any]) -> dict[str, Any]:
    """构建一条 case 节点。

    所有 conditionMatch / redirect 的 case 共享统一结构：
    ``{"value": ..., "rule": ..., "name": "case", "id": ""}``。
    """
    return {
        "value": value,
        "rule": rule,
        "name": "case",
        "id": "",
    }


def make_addfields_filter() -> dict[str, Any]:
    """构建 additional_fields_filter 节点（入口/子规则通用基础 filter）。"""
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


def make_redirect_filter(logtypes: list[str]) -> dict[str, Any]:
    """构建入口规则的 redirect filter（cases 覆盖所有 logtype）— 非 JSON 且非 KV 格式使用。"""
    cases: list[dict[str, Any]] = [
        _make_case(lt, {"fields": ["test"], "name": "removeFields", "id": ""})
        for lt in logtypes
    ]
    return {
        "name": "redirect",
        "field": "1",
        "id": "",
        "default": {"name": "none"},
        "cases": cases,
    }


def make_condition_match_filter(logtypes: list[str]) -> dict[str, Any]:
    """构建纯 JSON 入口规则的 conditionMatch filter。

    每个 case 的 value 格式固定为 ``original_log like '{logtype}'``，
    用于匹配包含特定 logtype 的 JSON 日志行。
    """
    cases: list[dict[str, Any]] = [
        _make_case(
            f"original_log like '{lt}'",
            {"fields": {"1": "1"}, "name": "addFields", "id": ""},
        )
        for lt in logtypes
    ]
    return {
        "cases": cases,
        "default": {"name": "none"},
        "name": "conditionMatch",
        "id": "",
    }


def make_logtype_mapping_filter(feature_field: str) -> dict[str, Any]:
    """构建日志类型映射 addFields filter（纯 JSON / 纯 KV 入口规则通用）。

    key 恒为 ``日志类型``，value 格式固定为 ``%{feature_field}``。

    CHANGED: 合并原 ``_make_feature_field_filter``（纯 JSON）与
    ``_make_kv_logtype_filter``（纯 KV）——二者输出 dict 逐字段一致，
    无需维护两份相同代码。
    """
    return {
        "fields": {"日志类型": f"%{{{feature_field}}}"},
        "name": "addFields",
        "id": "",
    }


def make_kv_condition_match_filter(
    logtypes: list[str], feature_field: str
) -> dict[str, Any]:
    """构建纯 KV 入口规则的 conditionMatch filter。

    每个 case 的 value 格式固定为 "{feature_field} like '{logtype}'"。
    """
    cases: list[dict[str, Any]] = [
        _make_case(
            f"{feature_field} like '{lt}'",
            {"fields": {"1": "1"}, "name": "addFields", "id": ""},
        )
        for lt in logtypes
    ]
    return {
        "cases": cases,
        "default": {"name": "none"},
        "name": "conditionMatch",
        "id": "",
    }


def make_syslog_kv_condition_match_filter(logtypes: list[str]) -> dict[str, Any]:
    """构建 syslog+KV 入口规则的 conditionMatch filter。

    每个 case 的 value 格式固定为 "original_log like '{logtype}'"。
    """
    cases: list[dict[str, Any]] = [
        _make_case(
            f"original_log like '{lt}'",
            {"fields": {"1": "1"}, "name": "addFields", "id": ""},
        )
        for lt in logtypes
    ]
    return {
        "cases": cases,
        "default": {"name": "none"},
        "name": "conditionMatch",
        "id": "",
    }