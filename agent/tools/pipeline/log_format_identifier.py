# -*- coding: utf-8 -*-
"""
[Step 1] 日志格式识别 — 采样 → LLM → 格式类型判定。

提供 _do_identify_log_format() 和 identify_log_format(@tool)。
"""

from __future__ import annotations

import json

import httpx
from agno.tools import tool

from agent.core.prompts import load_log_format_identify_prompt
from agent.shared.logger import get_logger
from agent.tools.enum_extract_tool import sample_logs
from agent.tools.pipeline.llm_client import (
    _call_llm_direct,
    _try_parse_json,
    normalize_log_format,
)

logger = get_logger("log_parser_pipeline")


def _do_identify_log_format(logs_str: str) -> str:
    """
    采样日志并由 LLM 识别格式类型（纯函数，供 chainlit_app 等直接调用）。

    Args:
        logs_str: 原始日志字符串（多行）

    Returns:
        JSON 字符串: {"format": "...", "delimiter": "...", "confidence": 0.95, ...}
    """
    if not logs_str or not logs_str.strip():
        return json.dumps(
            {"format": "unknown", "error": "日志内容为空", "confidence": 0},
            ensure_ascii=False,
        )

    try:
        # 采样 3 行供 LLM 分析（节省 token）
        sampled = sample_logs(logs_str, 3)
        if not sampled:
            return json.dumps(
                {"format": "unknown", "error": "采样结果为空", "confidence": 0},
                ensure_ascii=False,
            )

        prompt = load_log_format_identify_prompt().format(sampled_logs=sampled)
        response = _call_llm_direct(prompt, temperature=0.1, max_tokens=500, timeout=90)

        parsed = _try_parse_json(response)
        if parsed is None:
            logger.warning(f"[identify_log_format] LLM 返回非 JSON: {response[:200]}")
            return json.dumps(
                {
                    "format": "unknown",
                    "error": "LLM 返回非 JSON",
                    "raw_response": response[:500],
                    "confidence": 0,
                },
                ensure_ascii=False,
            )

        # 标准化字段名
        parsed.setdefault("format", "unknown")
        parsed.setdefault("format_detail", "unknown")
        parsed.setdefault("delimiter", None)
        parsed.setdefault("confidence", 0.5)
        parsed.setdefault("kv_connector", None)
        parsed.setdefault("kv_separator", None)
        parsed.setdefault("has_header", False)
        parsed.setdefault("has_header_feature", False)
        parsed.setdefault("space_count", 0)
        parsed.setdefault("log_feature_field", None)
        parsed.setdefault("feature_position", "kv_body")
        parsed.setdefault("feature_extract_regex", None)
        parsed.setdefault("reason", "")

        # CHANGED: 归一化 format 字段为枚举值，确保 Step 1 输出与 Step 2 一致
        parsed["format"] = normalize_log_format(parsed.get("format", "unknown"))
        parsed.setdefault("format_detail", parsed.get("format_detail") or parsed.get("format", ""))

        logger.info(
            f"[identify_log_format] feature_position={parsed['feature_position']}, "
            f"feature_extract_regex={parsed['feature_extract_regex']}, "
            f"feature_field={parsed['log_feature_field']}, "
            f"reason={parsed['reason'][:100]}"
        )

        return json.dumps(parsed, ensure_ascii=False)

    except httpx.HTTPStatusError as e:
        logger.error(f"[identify_log_format] API 错误: {e}")
        return json.dumps(
            {
                "format": "unknown",
                "error": f"LLM API 调用失败: {e.response.status_code}",
                "confidence": 0,
            },
            ensure_ascii=False,
        )
    except Exception as e:
        logger.error(f"[identify_log_format] 异常: {type(e).__name__}: {e}")
        return json.dumps(
            {"format": "unknown", "error": str(e), "confidence": 0},
            ensure_ascii=False,
        )


@tool(
    name="identify_log_format",
    description="识别日志文本的格式类型（json/kv/space/csv等）。输入 logs_str=原始日志字符串。返回 JSON 格式信息。",
)
def identify_log_format(logs_str: str) -> str:
    """Agno Agent 工具封装，委托给 _do_identify_log_format。"""
    return _do_identify_log_format(logs_str)