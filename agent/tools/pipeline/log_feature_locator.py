# -*- coding: utf-8 -*-
"""
Step 2a — 特征定位模块。

当 Step 1 识别为"日志头+JSON"格式时，通过 LLM 判断分类特征值
位于日志头还是 JSON body 中。
"""

from __future__ import annotations

import json
from typing import Any

from agent.core.prompts import load_log_feature_locate_prompt
from agent.shared.logger import get_logger
from agent.tools.enum_extract_tool import sample_logs
from agent.tools.pipeline.llm_client import _call_llm_direct, _try_parse_json

logger = get_logger("log_parser_pipeline")


def _escape_format_braces(text: str) -> str:
    """转义字符串中的花括号，防止 str.format() 误解析。
    
    Python str.format() 将 { } 解释为格式化占位符，但用户数据
    （如 JSON、日志样例）可能包含花括号。将它们转义为 {{ }}。
    
    Args:
        text: 待转义的字符串。
    
    Returns:
        转义后的字符串。
    """
    return text.replace('{', '{{').replace('}', '}}')


def _prepare_header_analysis(logs_str: str, format_type: str = "json", delimit: str = "=") -> dict:
    """用 HeaderExtractor 聚合日志头模式。

    Args:
        logs_str: 原始日志字符串。
        format_type: 日志格式（"json" 或 "kv"）。
        delimit: KV 格式的 key-value 连接符。
    """
    from agent.tools.pipeline.extractors.header_extractor import (
        HeaderExtractor,
        aggregate_headers,
    )
    return aggregate_headers(logs_str, format_type, delimit)


def _prepare_body_analysis(
    logs_str: str,
    feature_field: str,
    format_type: str = "json",
    delimit: str = "=",
    tab: str = " ",
) -> dict:
    """用 JsonExtractor 或 KvExtractor 分析 body 字段候选。

    Args:
        logs_str: 原始日志字符串。
        feature_field: Step 1 建议的特征字段。
        format_type: 日志格式（"json" 或 "kv"）。
        delimit: KV 格式的 key-value 连接符。
        tab: KV 格式的 key-value 分隔符。
    """
    if format_type == "kv":
        from agent.tools.pipeline.extractors.kv_extractor import KvExtractor
        extractor = KvExtractor(delimit, tab)
    else:
        from agent.tools.pipeline.extractors.json_extractor import JsonExtractor
        extractor = JsonExtractor()

    lines = [l for l in logs_str.strip().split("\n") if l.strip()][:200]

    # CHANGED: 添加日志，输出日志体示例（2026-06-08 调试）
    sample_lines = lines[:3]
    logger.info(f"[_prepare_body_analysis] 日志体示例（前3行）：")
    for i, line in enumerate(sample_lines, 1):
        logger.info(f"  行{i}: {line[:200]}")

    # 分析 Step 1 建议的 feature_field
    field_values: dict[str, set[str]] = {}
    if feature_field:
        vals: set[str] = set()
        for line in lines:
            v = extractor.extract_value(line, feature_field)
            if v is not None:
                vals.add(str(v))
        field_values[feature_field] = vals

    candidates = []
    for field_name, values in field_values.items():
        sample_vals = sorted(values)[:5]
        candidates.append({
            "field": field_name,
            "unique_values": len(values),
            "sample_values": sample_vals,
        })

    return {"candidates": candidates}


def locate_feature(
    logs_str: str,
    feature_field: str = "",
    format_type: str = "json",
    format_detail: str = "",
    delimit: str = "=",
    tab: str = " ",
) -> dict:
    """判断分类特征位置（header / body）。

    返回:
        {"feature_location": "body"|"header"|"unknown",
         "feature_field": str, "reason": str, "body_candidates": int}
    """
    if not logs_str or not logs_str.strip():
        return {"feature_location": "unknown", "feature_field": "", "reason": "日志为空", "body_candidates": 0}

    try:
        # 1. 准备分析数据
        header_analysis = _prepare_header_analysis(logs_str, format_type, delimit)
        body_analysis = _prepare_body_analysis(logs_str, feature_field, format_type, delimit, tab)

        header_clusters = header_analysis.get("clusters", [])
        header_distinct = len(header_clusters)
        body_candidates_count = len(body_analysis.get('candidates', []))

        # 2. 构建 prompt
        # CHANGED: 转义花括号，防止 str.format() 误解析
        header_json = _escape_format_braces(json.dumps(
            {"unique_patterns": header_distinct, "patterns": header_clusters[:10]},
            ensure_ascii=False,
        ))
        body_json = _escape_format_braces(json.dumps(body_analysis, ensure_ascii=False))
        sampled = _escape_format_braces(sample_logs(logs_str, 5))

        prompt = load_log_feature_locate_prompt().format(
            header_analysis=header_json,
            body_analysis=body_json,
            sample_count="5",
            sampled_logs=sampled,
        )

        logger.info(
            f"[locate_feature] 调用 LLM, "
            f"header_patterns={header_distinct}, "
            f"body_candidates={body_candidates_count}"
        )

        # 3. 调用 LLM（无兜底策略）
        response = _call_llm_direct(prompt, temperature=0.1, max_tokens=300, timeout=30)
        parsed = _try_parse_json(response)

        if parsed and parsed.get("feature_location") in ("body", "header", "unknown"):
            result = {
                "feature_location": parsed["feature_location"],
                "feature_field": parsed.get("feature_field", ""),
                "reason": parsed.get("reason", ""),
                "body_candidates": body_candidates_count,
            }
            logger.info(
                f"[locate_feature] LLM 判定: location={result['feature_location']}, "
                f"field={result['feature_field']}, reason={result['reason'][:100]}"
            )
            return result

        logger.warning(f"[locate_feature] LLM 返回无效: {response[:200]}")
        return {"feature_location": "unknown", "feature_field": "", "reason": "LLM返回无效", "body_candidates": body_candidates_count}

    except Exception as e:
        logger.error(f"[locate_feature] 异常: {type(e).__name__}: {e}")
        # CHANGED: 无兜底策略，直接返回 unknown
        return {"feature_location": "unknown", "feature_field": "", "reason": f"定位异常: {e}", "body_candidates": 0}
