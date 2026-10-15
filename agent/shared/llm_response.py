# -*- coding: utf-8 -*-
"""LLM 响应解析的共享原语（#345）。

「剥 markdown 围栏 + json.loads + 兜底」曾以三种写法散布七个文件；
此处收口为唯一实现，既有差异项做成显式选项：

- :func:`strip_code_fences` —— 围栏剥离原语。抛错风格（json.loads 异常
  上抛供调用方重试）的解析只消费它，错误语义保持不变；
- :func:`parse_json_object` —— None 风格解析，可选尾随逗号修复与
  ``{...}`` 块提取兜底（均为历史实现既有行为的显式化）。
"""

from __future__ import annotations

import json
import re

_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")
_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def strip_code_fences(text: str) -> str:
    """剥掉 markdown 代码围栏：去除以 ````` 开头的围栏行。

    无围栏（不以 ````` 开头）时仅去首尾空白原样返回。
    """
    text = text.strip()
    if not text.startswith("```"):
        return text
    lines = [line for line in text.split("\n") if not line.strip().startswith("```")]
    return "\n".join(lines).strip()


def parse_json_object(
    text: str,
    *,
    repair_trailing_comma: bool = False,
    extract_block: bool = False,
) -> dict | None:
    """解析 LLM 响应中的 JSON 对象；失败返回 None。

    Args:
        text: LLM 原始响应。
        repair_trailing_comma: 首次解析失败后先修复 ``]``/``}`` 前的
            尾随逗号再试（历史行为来自 log 分类后处理）。
        extract_block: 仍失败时以 ``\\{.*\\}`` 提取首个 ``{...}`` 块再试
            （历史行为来自 pipeline 客户端与字段解析）。
    """
    if not text or not text.strip():
        return None
    candidate = strip_code_fences(text)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    if repair_trailing_comma:
        cleaned = _TRAILING_COMMA_RE.sub(r"\1", candidate)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
    if extract_block:
        match = _JSON_BLOCK_RE.search(candidate)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return None
