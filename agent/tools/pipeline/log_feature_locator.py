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


def _prepare_header_analysis(logs_str: str) -> dict:
    """用 HeaderExtractor 聚合日志头模式。"""
    from agent.tools.pipeline.extractors.header_extractor import (
        HeaderExtractor,
        aggregate_headers,
    )
    return aggregate_headers(logs_str)


def _prepare_body_analysis(
    logs_str: str,
    feature_field: str,
) -> dict:
    """用 JsonExtractor 分析 body 字段候选。"""
    from agent.tools.pipeline.extractors.json_extractor import JsonExtractor

    extractor = JsonExtractor()
    lines = [l for l in logs_str.strip().split("\n") if l.strip()][:200]

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
    format_detail: str = "",
) -> dict:
    """判断分类特征位置（header / body）。

    返回:
        {"feature_location": "body"|"header"|"unknown",
         "feature_field": str, "reason": str}
    """
    if not logs_str or not logs_str.strip():
        return {"feature_location": "unknown", "feature_field": "", "reason": "日志为空"}

    try:
        # 1. 准备分析数据
        header_analysis = _prepare_header_analysis(logs_str)
        body_analysis = _prepare_body_analysis(logs_str, feature_field)

        header_clusters = header_analysis.get("clusters", [])
        header_distinct = len(header_clusters)

        # 2. 构建 prompt
        header_json = json.dumps(
            {"unique_patterns": header_distinct, "patterns": header_clusters[:10]},
            ensure_ascii=False,
        )
        body_json = json.dumps(body_analysis, ensure_ascii=False)
        sampled = sample_logs(logs_str, 5)

        prompt = load_log_feature_locate_prompt().format(
            header_analysis=header_json,
            body_analysis=body_json,
            sample_count="5",
            sampled_logs=sampled,
        )

        logger.info(
            f"[locate_feature] 调用 LLM, "
            f"header_patterns={header_distinct}, "
            f"body_candidates={len(body_analysis.get('candidates', []))}"
        )

        # 3. 调用 LLM（短超时，失败时快速降级）
        response = _call_llm_direct(prompt, temperature=0.1, max_tokens=300, timeout=30)
        parsed = _try_parse_json(response)

        if parsed and parsed.get("feature_location") in ("body", "header", "unknown"):
            result = {
                "feature_location": parsed["feature_location"],
                "feature_field": parsed.get("feature_field", feature_field),
                "reason": parsed.get("reason", ""),
            }
            logger.info(
                f"[locate_feature] LLM 判定: location={result['feature_location']}, "
                f"field={result['feature_field']}, reason={result['reason'][:100]}"
            )
            return result

        logger.warning(f"[locate_feature] LLM 返回无效: {response[:200]}")
        return {"feature_location": "unknown", "feature_field": feature_field, "reason": "LLM返回无效"}

    except Exception as e:
        logger.warning(f"[locate_feature] 异常: {type(e).__name__}: {e}")
        # 降级：保持 Step 1 建议，走 body 路径
        return {"feature_location": "body", "feature_field": feature_field, "reason": f"定位异常降级: {e}"}