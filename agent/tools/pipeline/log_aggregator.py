# -*- coding: utf-8 -*-
"""
[Step 2] 按日志格式聚合 — 将同格式的日志行按 feature_field 分组，统计分布。

依赖: log_feature_extractor (行级字段提取)
"""

from __future__ import annotations

import json
import re as _re
from collections import Counter, defaultdict

from agent.shared.logger import get_logger
from agent.tools.pipeline.log_feature_extractor import (
    _try_extract_json_feature,
    _try_extract_kv_feature,
)

logger = get_logger("log_parser_pipeline")


def _aggregate_by_log_type(
    lines_by_type: dict[str, list[str]],
    feature_field: str,
    log_format_map: dict[str, str],
    format_details: dict[str, dict],
) -> dict[str, list[dict]]:
    """
    按格式类型分别聚合特征字段的频次。

    Args:
        lines_by_type: {"JSON": [...], "KV": [...], ...}
        feature_field: LLM 识别的特征字段路径
        log_format_map: {"JSON": "JSON", "kv": "KV", ...}（归一化后）
        format_details: LLM 返回的每种格式的详细配置

    Returns:
        {"JSON": [{"line": ..., "feature_value": ..., "source_line_index": ...}, ...],
         "KV": [...], ...}
    """
    sampled: dict[str, list[dict]] = defaultdict(list)
    max_samples_per_type = 200  # 每种格式最多取 200 条样本避免 OOM

    for format_type, lines in lines_by_type.items():
        normalized_type = log_format_map.get(format_type, format_type).upper()
        format_info = format_details.get(format_type, {})

        # 限制行数
        sample_lines = lines[:max_samples_per_type] if len(lines) > max_samples_per_type else lines

        for idx, line in enumerate(sample_lines):
            try:
                if normalized_type == "JSON":
                    value = _try_extract_json_feature(line, feature_field)
                else:
                    value = _try_extract_kv_feature(
                        line, feature_field, format_type, format_info
                    )
                sampled[normalized_type].append({
                    "line": line[:500],  # 截断过长行
                    "feature_value": value,
                    "source_line_index": idx,
                })
            except Exception:
                sampled[normalized_type].append({
                    "line": line[:500],
                    "feature_value": None,
                    "source_line_index": idx,
                })

    return dict(sampled)


def _aggregate_fields(
    parsed_lines: list[dict],
    log_type: str,
    format_info: dict,
    feature_fields: list[str],
    log_format: str,
) -> dict[str, Counter]:
    """
    按业务字段聚合多字段的频次分布。

    Args:
        parsed_lines: 已解析的行列表
        log_type: 日志格式类型
        format_info: LLM 返回的格式详情
        feature_fields: 需要聚合的特征字段列表
        log_format: 标准化格式

    Returns:
        {field_name: Counter({value: count, ...}), ...}
    """
    from agent.tools.pipeline.log_feature_extractor import (
        _try_extract_json_feature,
        _try_extract_kv_feature,
    )

    field_distributions: dict[str, Counter] = defaultdict(Counter)
    normalized_type = (log_format or log_type).upper()

    for line_info in parsed_lines:
        raw_line = line_info.get("line", "")
        for field in feature_fields:
            if not field:
                continue
            try:
                if normalized_type == "JSON":
                    value = _try_extract_json_feature(raw_line, field)
                else:
                    value = _try_extract_kv_feature(
                        raw_line, field, log_type, format_info
                    )
                if value is not None:
                    field_distributions[field][str(value)] += 1
            except Exception:
                continue

    return dict(field_distributions)


def _build_log_analysis(
    log_type: str,
    sampled: list[dict],
    format_info: dict,
    log_format: str,
    feature_fields: list[str],
) -> dict:
    """构建 Step 2 输出中的 analysis 字段。"""
    total = len(sampled)
    extracted_count = sum(1 for s in sampled if s.get("feature_value") is not None)
    field_distributions = _aggregate_fields(
        sampled, log_type, format_info, feature_fields, log_format
    )

    return {
        "total_lines": total,
        "extracted_lines": extracted_count,
        "extraction_rate": round(extracted_count / total, 3) if total > 0 else 0.0,
        "field_distributions": {
            field: dict(counter.most_common(20))
            for field, counter in field_distributions.items()
        },
    }


def _build_fallback_details(
    lines: list[str],
    log_format: str,
    feature_field: str,
) -> dict:
    """构建兜底分支的 classification_details（当 LLM 返回 None 或解析失败时）。"""
    sampled = lines[:200]  # 最多取 200 行
    samples_for_analysis: list[dict] = []

    for idx, line in enumerate(sampled):
        if log_format == "JSON":
            feature_value = _try_extract_json_feature(line, feature_field)
        else:
            feature_value = _try_extract_kv_feature(line, feature_field, log_format.lower(), {})
        samples_for_analysis.append({
            "line": line[:500],
            "feature_value": feature_value,
            "source_line_index": idx,
        })

    return {
        "log_type": log_format.lower(),
        "log_format": log_format,
        "log_format_detail": f"fallback/{log_format.lower()}",
        "feature_field": feature_field,
        "feature_values": {},
        "samples": samples_for_analysis,
        "analysis": {
            "total_lines": len(sampled),
            "extracted_lines": sum(1 for s in samples_for_analysis if s.get("feature_value")),
        },
    }


def aggregate_by_format(
    lines_by_type: dict[str, list[str]],
    feature_field: str,
    log_type_details: dict,
    parsed: dict,
) -> None:
    """
    Step 2 主入口：按格式聚合，将结果写入 parsed["classification_details"]。

    遍历每种格式 → 提取 feature_field 值 → 统计分布 → 构建 classification_details。
    """
    # 1. 归一化格式映射
    log_format_map: dict[str, str] = {}
    for raw_key, detail in (log_type_details or {}).items():
        normalized = (detail.get("log_format") or "UNKNOWN").upper()
        log_format_map[raw_key] = normalized

    # 2. 按类型提取特征值
    sampled_by_type = _aggregate_by_log_type(
        lines_by_type, feature_field, log_format_map, log_type_details
    )

    # 3. 构建 classification_details
    classification_details: list[dict] = []
    all_feature_fields = [feature_field]

    for log_type, sampled_lines in sorted(sampled_by_type.items()):
        format_info = log_type_details.get(log_type, {})
        log_format = format_info.get("log_format", log_type)

        detail: dict = {
            "log_type": log_type.lower(),
            "log_format": log_format,
            "log_format_detail": format_info.get("log_format_detail", log_format),
            "feature_field": feature_field,
            "feature_values": {},
            "samples": sampled_lines[:50],  # 每种类型最多保存 50 条样本
            "analysis": _build_log_analysis(
                log_type, sampled_lines, format_info, log_format, all_feature_fields
            ),
        }
        classification_details.append(detail)

    # 4. 写入 parsed
    parsed["classification_details"] = classification_details

    # 5. 兜底：如果没有通过 _aggregate_by_log_type 产出任何结果，使用 raw_samples 构建
    if not classification_details and parsed.get("raw_samples"):
        logger.warning("[aggregate_by_format] LLM 未返回有效结果，使用 raw_samples 构建 classification_details")
        raw_samples = parsed["raw_samples"]
        # 重新按格式分组 raw_samples
        fallback_by_type: dict[str, list[str]] = defaultdict(list)
        for sample_str in raw_samples:
            # 简单按行内容判断是否为 JSON
            stripped = sample_str.strip()
            if stripped.startswith("{") and stripped.endswith("}"):
                fallback_by_type["json"].append(sample_str)
            else:
                fallback_by_type["kv"].append(sample_str)

        for fallback_type, fallback_lines in fallback_by_type.items():
            fallback_format = "JSON" if fallback_type == "json" else "KV"
            detail = _build_fallback_details(fallback_lines, fallback_format, feature_field)
            classification_details.append(detail)
        parsed["classification_details"] = classification_details