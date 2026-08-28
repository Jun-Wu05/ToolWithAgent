"""提供与界面无关的确定性 JSON 解析。"""

from __future__ import annotations

import json
import re
from typing import Any


def parse_json_safe(text: str) -> dict[str, Any] | None:
    """解析 JSON 对象，兼容 Markdown 代码块与正文中的对象片段。"""
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return None
