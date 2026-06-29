# -*- coding: utf-8 -*-
"""
JSON 提取工具函数。

统一的 JSON 相关操作模块：
- 通过点分隔路径提取嵌套字段
- 从混合格式日志行中提取 JSON body
- 组合式 JSON 特征提取（含 syslog 头部回退）
"""

from __future__ import annotations

import json
import re as _re
from typing import Any

# 固定正则：从第一个 `{` 匹配到最后一个 `}`（通过 [\S\s] 支持换行）
_JSON_BODY_RE = _re.compile(r"\{[\S\s]*\}")


def get_nested_json_value(obj: dict, path: str) -> Any:
    """沿点分隔路径遍历嵌套字典。

    Example:
        get_nested_json_value({"a": {"b": 1}}, "a.b") → 1
        get_nested_json_value({"a": 1}, "a.b") → None

    Args:
        obj:  JSON 解析后的字典。
        path: 点分隔的字段路径，例如 ``"event.type"``。

    Returns:
        路径处的值；如果任意键缺失或中间节点不是字典则返回 None。
    """
    if not path:
        return None
    keys = path.split(".")
    current: Any = obj
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
            if current is None:
                return None
        else:
            return None
    return current


def extract_json_body(line: str) -> str | None:
    """使用固定正则从日志行中提取 JSON body 子串。

    从第一个 ``{`` 匹配到最后一个 ``}``（贪婪，dotall 模式）。

    Args:
        line: 单条日志行。

    Returns:
        JSON body 字符串，未匹配到则返回 None。
    """
    m = _JSON_BODY_RE.search(line)
    return m.group(0) if m else None


def strip_header_to_body(
    line: str, header_end_marker: str = "", *, is_json: bool = True
) -> str:
    """剥离日志头，返回 body 部分。

    - ``is_json=True``（JSON / 日志头+JSON）：优先用 :func:`extract_json_body`
      从第一个 ``{`` 取到最后一个 ``}``，完全不依赖 ``header_end_marker``，
      避免 syslog 头部含多个空格时 ``split(marker, 1)`` 从首个空格误切断的问题；
      当行内没有 ``{...}`` 时，降级使用 ``header_end_marker`` 分割。
    - ``is_json=False``（KV / 其他格式）：保持原有
      ``line.split(header_end_marker, 1)`` 行为不变。

    Args:
        line:              完整日志行。
        header_end_marker: 头部与 body 的分隔符（JSON 格式下仅作降级使用）。
        is_json:           是否按 JSON 格式剥离头部。

    Returns:
        剥离头部后的 body；标记为空或未找到时返回原始行。
    """
    if not line:
        return line

    if is_json:
        body = extract_json_body(line)
        if body:
            return body
        # 行内无 {...}：降级使用 header_end_marker
        if header_end_marker:
            parts = line.split(header_end_marker, 1)
            if len(parts) == 2:
                return parts[1]
        return line

    # 非 JSON：保持原 split(header_end_marker, 1) 行为
    if header_end_marker:
        parts = line.split(header_end_marker, 1)
        if len(parts) == 2:
            return parts[1]
    return line


def try_extract_json_feature(line: str, feature_field: str) -> Any:
    """从 JSON 日志行中提取字段值。

    支持两种格式：
    1. 纯 JSON 行 —— 直接 ``json.loads``。
    2. syslog 头部 + JSON —— 找到第一个 ``{`` 到最后一个 ``}``，
       解析该子串作为回退。

    Args:
        line:           单条日志行。
        feature_field:  字段名（支持点分隔路径）。

    Returns:
        字段值，解析或查找失败返回 None。
    """
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        # 回退：syslog 头部 + JSON
        json_start = line.find("{")
        json_end = line.rfind("}")
        if json_start != -1 and json_end > json_start:
            try:
                obj = json.loads(line[json_start:json_end + 1])
            except (json.JSONDecodeError, ValueError):
                return None
        else:
            return None

    return get_nested_json_value(obj, feature_field)