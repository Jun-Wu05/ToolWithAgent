# -*- coding: utf-8 -*-
"""
[Step 2 // Step 2.5 底层支撑] 从单行日志中提取 KV / JSON / CEF 字段值。

被 log_aggregator (Step 2) 和 log_field_aggregator (Step 2.5) 使用。
纯行级解析，不依赖 LLM 或其他 pipeline 模块。
"""

from __future__ import annotations

import json
import re as _re
from typing import Any


def _smart_split(text: str, sep: str) -> list[str]:
    """智能拆分，考虑引号内的分隔符"""
    if sep == " ":
        parts = []
        current: list[str] = []
        in_quote = False
        quote_char = ""
        for ch in text:
            if ch in ('"', "'") and not in_quote:
                in_quote = True
                quote_char = ch
                current.append(ch)
            elif ch == quote_char and in_quote:
                in_quote = False
                current.append(ch)
            elif ch == sep and not in_quote:
                parts.append("".join(current))
                current = []
            else:
                current.append(ch)
        if current:
            parts.append("".join(current))
        return parts
    else:
        return text.split(sep)


def _parse_kv_line(
    line: str, kv_connector: str = "=", kv_separator: str = " "
) -> list[tuple[str, str]]:
    """解析一行 KV 格式日志"""
    pairs: list[tuple[str, str]] = []
    tokens = _smart_split(line, kv_separator)
    for token in tokens:
        token = token.strip().strip('"').strip("'")
        if kv_connector in token:
            key, _, value = token.partition(kv_connector)
            key = key.strip().strip('"').strip("'").strip()
            value = value.strip().strip('"').strip("'").strip()
            if key:
                pairs.append((key, value))
    return pairs


def _get_nested_value(obj: dict, path: str) -> Any:
    """从嵌套 JSON 对象中按点分隔路径获取值，如 'event.type'"""
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


def _try_extract_json_feature(line: str, feature_field: str) -> Any:
    """从一行 JSON 日志中提取 feature_field 的值（含日志头+JSON 子串回退）。"""
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        # 支持"日志头+JSON"格式：提取第一个 { 到最后一个 } 之间的 JSON 子串
        json_start = line.find("{")
        json_end = line.rfind("}")
        if json_start != -1 and json_end > json_start:
            try:
                obj = json.loads(line[json_start:json_end + 1])
            except (json.JSONDecodeError, ValueError):
                return None
        else:
            return None
    return _get_nested_value(obj, feature_field)


def _kv_from_token(token: str, pairs: dict[str, str]) -> None:
    """从一个 token 中提取 key=value 或 key:value 对。"""
    for connector in ("=", ":", " "):
        if connector in token:
            key, sep, value = token.partition(connector)
            key = key.strip().strip('"').strip("'").strip()
            value = value.strip().strip('"').strip("'").strip()
            if key and key not in pairs:
                pairs[key] = value
            return


def _kv_from_space_line(line: str, pairs: dict[str, str]) -> None:
    """从空格分隔的行中提取 key=value 对（正则匹配）。"""
    # 匹配 patterns like key=value 或 key="value" 或 key:value
    pattern = _re.compile(r'(\S+)([=:])(?:"([^"]*)"|\'([^\']*)\'|(\S+))')
    for m in pattern.finditer(line):
        key = m.group(1).strip()
        value = m.group(3) or m.group(4) or m.group(5)
        if key and key not in pairs:
            pairs[key] = value


def _kv_from_cef_style(line: str, pairs: dict[str, str]) -> None:
    """
    从 CEF 风格的扩展字段中提取 key=value 对。
    CEF 格式: CEF:Version|Device Vendor|...|Extension
    Extension 为 key=value 空格分隔的对。
    """
    # 提取 CEF 扩展部分（最后一个 | 之后）
    if "|" in line:
        cef_parts = line.split("|")
        # CEF 扩展从第 8 个字段开始（下标 7）
        # 但常见的是最后一个 | 之后的所有内容
        extension = cef_parts[-1]
        # 按空格拆分扩展字段中的 key=value 对
        for token in extension.split():
            token = token.strip()
            if "=" in token and not token.startswith("="):
                key, sep, value = token.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in pairs:
                    pairs[key] = value

    # 同时也尝试按 key=value 正则匹配整行
    _kv_from_space_line(line, pairs)


def _try_extract_kv_feature(
    line: str,
    feature_field: str,
    format_type: str,
    format_info: dict | None = None,
) -> Any:
    """
    从非 JSON 日志行中提取 feature_field 的值。

    策略（按优先级）：
    1. semicolon/comma：按分隔符拆分 → 每个 token 按 key=value 解析
    2. kv：使用 format_info 中的 kv_connector/kv_separator
    3. space：用正则 /\S+=\S+/ 匹配 key=value 对
    4. cef：查找 CEF 扩展字段中的 key=value 对
    5. 兜底：遍历行中所有 key=value 对查找匹配
    """
    if format_info is None:
        format_info = {}

    pairs: dict[str, str] = {}

    # 【优先级 0】LLM 识别特征值在日志头部固定位置，用 LLM 生成的正则提取
    feature_position = format_info.get("feature_position", "kv_body")
    if feature_position == "header_regex":
        extract_regex = format_info.get("feature_extract_regex")
        if extract_regex:
            try:
                m = _re.search(extract_regex, line)
                if m:
                    return m.group(1) if m.lastindex else m.group(0)
            except _re.error:
                pass
    # 【优先级 0.5】positional: 按固定列位置提取
    if feature_position == "positional":
        column_index = format_info.get("column_index")
        if column_index is not None:
            try:
                col_idx = int(column_index)
                if format_type in ("semicolon", "comma"):
                    tokens = _smart_split(line, ";" if format_type == "semicolon" else ",")
                else:
                    tokens = _re.split(r"\s+", line.strip())
                tokens = [t for t in tokens if t]
                if 0 <= col_idx < len(tokens):
                    return tokens[col_idx].strip().strip('"').strip("'")
            except (ValueError, IndexError):
                pass

    if format_type == "semicolon":
        # 分号分隔 → 按 ; 拆分 → 每个 token 可能是 key=value
        tokens = line.split(";")
        for token in tokens:
            token = token.strip().strip('"').strip("'")
            _kv_from_token(token, pairs)
    elif format_type == "comma":
        # 逗号分隔 → 注意引号内的逗号
        tokens = _smart_split(line, ",")
        for token in tokens:
            token = token.strip().strip('"').strip("'")
            _kv_from_token(token, pairs)
    elif format_type == "kv":
        kv_connector = format_info.get("kv_connector", "=")
        kv_separator = format_info.get("kv_separator", " ")
        kv_pairs = _parse_kv_line(line, kv_connector, kv_separator)
        for k, v in kv_pairs:
            pairs[k] = v
    elif format_type == "space":
        # 空格分隔：先尝试按 key=value 正则匹配
        _kv_from_space_line(line, pairs)
        # 也尝试用 CEF 的 key=value 模式
        if feature_field not in pairs:
            _kv_from_cef_style(line, pairs)
    elif format_type == "cef":
        _kv_from_cef_style(line, pairs)
    else:
        # unknown：遍历所有可能的 key=value 对
        _kv_from_token(line, pairs)
        _kv_from_space_line(line, pairs)
        _kv_from_cef_style(line, pairs)

    # 查找 feature_field（支持嵌套路径如 "event.type"）
    field_parts = feature_field.split(".")
    for k, v in pairs.items():
        if k == field_parts[0]:
            return v
        # 如果 feature_field 是单字段路径但 key 以 / 分隔（如 SHELL/6/SHELL_CMD）
        if feature_field in k:
            return v

    # 如果没找到精确匹配，尝试模糊匹配：去掉前导路径部分
    for k, v in pairs.items():
        # e.g. SHELL/6/SHELL_CMD contains SHELL_CMD
        if "/" in feature_field:
            last_part = feature_field.rsplit("/", 1)[-1]
            if k == last_part:
                return v
        if "/" in k:
            last_part = k.rsplit("/", 1)[-1]
            if last_part == feature_field or last_part == feature_field.rsplit("/", 1)[-1]:
                return v

    return None