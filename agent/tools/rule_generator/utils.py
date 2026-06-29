"""通用工具模块。

提供规则生成过程中使用的通用辅助函数：时间戳、UUID、值转换、
分隔符转义，以及引号/括号感知的 KV 行解析器。

本模块为纯函数模块，不依赖项目内其他模块。
"""

import json
import time
import uuid
from typing import Any


# ---------------------------------------------------------------------------
# 时间与标识
# ---------------------------------------------------------------------------

def now_ms() -> int:
    """返回当前毫秒级时间戳（int）。"""
    return int(time.time() * 1000)


def new_uuid() -> str:
    """返回标准 UUID 字符串（小写，含连字符）。"""
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# 值转换
# ---------------------------------------------------------------------------

def value_to_str(value: Any) -> str:
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


# ---------------------------------------------------------------------------
# 分隔符转义
# ---------------------------------------------------------------------------

def escape_delimit(delimit: str) -> str:
    """转义 delimit 字段中的特殊字符。

    CHANGED: 补充语义化名称映射（之前标注为 TODO，现已实现）。

    当前转义规则：
    - "space" → \\s（空格）
    - "comma" → `,`（逗号）
    - "semicolon" → `;`（分号）
    - "\\t" → \\t（制表符）
    - 其他（";", ",", "||" 等）→ 保持原样

    Args:
        delimit: 字段分隔符（键值对之间的分隔符）

    Returns:
        转义后的分隔符字符串
    """
    _SEMANTIC_MAP: dict[str, str] = {
        "space": "\\s",
        "comma": ",",
        "semicolon": ";",
        "tab": "\\t",
    }
    mapped = _SEMANTIC_MAP.get(delimit.lower())
    if mapped is not None:
        return mapped
    if delimit == "\\t":
        return "\\t"
    return delimit


# ---------------------------------------------------------------------------
# KV 行解析（引号/括号感知状态机）
# ---------------------------------------------------------------------------

def split_kv_line_quote_aware(
    text: str,
    delimit: str = " ",
    tab: str = "=",
) -> list[str]:
    """引号/括号感知的 KV 行拆分器，返回去重后的 key 列表。

    CHANGED: 使用状态机逐字符扫描替代正则，正确处理引号和括号/花括号
    内的嵌套结构（如 ``process_tree=[{...,"cmdline":"a=b c"}]`` 中
    ``a=b`` 不会被误识别为字段）。

    状态跟踪：
    - ``in_double_quote``: 是否在 ``"..."`` 内
    - ``in_single_quote``: 是否在 ``'...'`` 内
    - ``bracket_depth``: 方括号 ``[...]`` 嵌套深度
    - ``brace_depth``: 花括号 ``{...}`` 嵌套深度
    - ``prev_escape``: 前一字符是否为转义符 ``\\``（仅在引号内生效）

    规则：
    - 仅当 "深度全为 0 且不在任何引号内" 时，分隔符才视为字段边界
    - key 提取：在 segment 内找第一个 ``tab`` 位置，``tab`` 之前为 key

    Args:
        text: KV 格式文本（单行或多行）。
        delimit: 字段分隔符（``"space"`` / ``"comma"`` / ``"semicolon"`` 或实际字符）。
        tab: 键值分隔符（如 ``"="`` ``":"``）。

    Returns:
        去重后的 key 列表（保持首次出现顺序）。
    """
    # 语义化名称 → 实际字符
    _DELIMIT_MAP: dict[str, str] = {
        "space": " ",
        "comma": ",",
        "semicolon": ";",
        "tab": "\t",
    }
    actual_delimit = _DELIMIT_MAP.get(delimit.lower(), delimit)
    is_space_delimit = actual_delimit == " "

    segments: list[str] = []
    current_segment: list[str] = []

    in_double_quote = False
    in_single_quote = False
    bracket_depth = 0
    brace_depth = 0
    prev_escape = False

    for ch in text:
        # --- 转义字符处理（仅在引号内生效） ---
        if prev_escape:
            current_segment.append(ch)
            prev_escape = False
            continue

        if ch == "\\" and (in_double_quote or in_single_quote):
            current_segment.append(ch)
            prev_escape = True
            continue

        # --- 引号状态切换 ---
        if ch == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            current_segment.append(ch)
            continue
        if ch == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            current_segment.append(ch)
            continue

        # --- 括号深度跟踪（仅在非引号状态） ---
        if not in_double_quote and not in_single_quote:
            if ch == "[":
                bracket_depth += 1
                current_segment.append(ch)
                continue
            if ch == "]":
                bracket_depth = max(0, bracket_depth - 1)
                current_segment.append(ch)
                continue
            if ch == "{":
                brace_depth += 1
                current_segment.append(ch)
                continue
            if ch == "}":
                brace_depth = max(0, brace_depth - 1)
                current_segment.append(ch)
                continue

        # --- 分隔符检测（仅在深度全为 0 且不在引号内） ---
        at_depth_zero = (
            bracket_depth == 0
            and brace_depth == 0
            and not in_double_quote
            and not in_single_quote
        )

        if at_depth_zero:
            if is_space_delimit and ch.isspace():
                segments.append("".join(current_segment))
                current_segment = []
            elif ch == actual_delimit:
                segments.append("".join(current_segment))
                current_segment = []
            else:
                current_segment.append(ch)
        else:
            current_segment.append(ch)

    # 最后一个 segment
    if current_segment:
        segments.append("".join(current_segment))

    # --- 从每个 segment 提取 key ---
    keys: list[str] = []
    seen: set[str] = set()
    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        idx = seg.find(tab)
        if idx > 0:
            key = seg[:idx].strip()
            if key and key not in seen:
                seen.add(key)
                keys.append(key)

    return keys


def extract_kv_keys(text: str, delimit: str = " ", tab: str = "=") -> list[str]:
    """从 KV 格式文本中提取所有字段名（key）。

    CHANGED: 使用引号/括号感知的状态机解析器（``split_kv_line_quote_aware``）
    替代正则表达式，正确处理引号和括号内的嵌套结构。

    Args:
        text: KV 格式文本（单行或多行）。
        delimit: 字段分隔符（``"space"`` / ``"comma"`` / ``"semicolon"`` 或实际字符）。
        tab: 键值分隔符（如 ``"="`` ``":"``）。

    Returns:
        去重后的 key 列表（保持首次出现顺序）。
    """
    return split_kv_line_quote_aware(text, delimit, tab)