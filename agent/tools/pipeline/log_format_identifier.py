# -*- coding: utf-8 -*-
"""
日志格式识别（Step 1）。

采样日志行 → 调用 LLM → 判定格式类型。
当前仅支持 JSON 格式，非 JSON 格式返回 UNSUPPORTED 状态。
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
    """采样日志并由 LLM 识别格式类型。

    参数:
        logs_str: 原始日志字符串（多行）

    返回:
        JSON 字符串，包含格式信息和置信度。
        非 JSON 格式时返回 status="UNSUPPORTED"。
    """
    if not logs_str or not logs_str.strip():
        return json.dumps(
            {"format": "unknown", "error": "日志内容为空", "confidence": 0},
            ensure_ascii=False,
        )

    try:
        # 采样 3 行供 LLM 分析
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

        # 填充默认字段
        parsed.setdefault("format", "unknown")
        parsed.setdefault("format_detail", "unknown")
        parsed.setdefault("delimiter", None)
        parsed.setdefault("confidence", 0.5)
        parsed.setdefault("kv_connector", None)
        parsed.setdefault("kv_separator", None)
        parsed.setdefault("has_header", False)
        # CHANGED: 将 LLM 返回的 kv_connector/kv_separator 映射为 delimit/tab
        # 下游代码使用 delimit/tab 字段名（log_classifier.py）
        if "kv_connector" in parsed and parsed["kv_connector"] is not None:
            parsed["delimit"] = parsed["kv_connector"]
        
        # CHANGED: kv_separator 值映射（支持中文描述和代码格式）
        # 注意："space" 保持为字符串 "space"，让 KvExtractor 自动转为 \s+
        separator_map = {
            "空格": "space",     # 映射为 "space"，KvExtractor 会自动转为 \s+
            "space": "space",    # 保持为 "space"，KvExtractor 自动转为 \s+
            "分号": ";",
            "semicolon": ";",
            "逗号": ",",        # 英文逗号
            "comma": ",",
            "中文逗号": "，",   # 中文逗号
            "管道": "||",
            "pipe": "||",
            "tab": "\t",
        }
        if "kv_separator" in parsed and parsed["kv_separator"] in separator_map:
            parsed["tab"] = separator_map[parsed["kv_separator"]]
        elif "kv_separator" in parsed and parsed["kv_separator"] is not None:
            parsed["tab"] = parsed["kv_separator"]
        parsed.setdefault("header_end_marker", "")
        parsed.setdefault("has_header_feature", False)  # CHANGED: 新增字段
        parsed.setdefault("feature_field", "")  # CHANGED: 新增字段
        parsed.setdefault("feature_location", "unknown")  # CHANGED: 新增字段
        parsed.setdefault("reason", "")

        # CHANGED: has_header=false 时强制 has_header_feature=false
        if not parsed.get("has_header"):
            parsed["has_header_feature"] = False

        # 归一化 format 字段为枚举值
        parsed["format"] = normalize_log_format(parsed.get("format", "unknown"))
        parsed.setdefault("format_detail", parsed.get("format_detail") or parsed.get("format", ""))

        # 非 JSON 格式标记为不支持
        if parsed["format"] == "unknown":
            logger.info(
                f"[identify_log_format] 无法识别的格式"
            )
            parsed["status"] = "UNSUPPORTED"
            parsed["reason"] = "无法识别日志格式"

        logger.info(
            f"[identify_log_format] format={parsed['format']}, "
            f"has_header={parsed.get('has_header')}, "
            f"header_end_marker='{parsed.get('header_end_marker', '')}'"
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
    description="识别日志文本的格式类型。当前仅支持 JSON 格式。输入 logs_str=原始日志字符串，返回 JSON 格式信息。",
)
def identify_log_format(logs_str: str) -> str:
    """日志格式识别工具，委托给 _do_identify_log_format。"""
    return _do_identify_log_format(logs_str)