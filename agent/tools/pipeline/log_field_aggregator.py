# -*- coding: utf-8 -*-
"""
[Step 2.5] 按业务字段聚合 — 跨格式统一的字段分布统计。

在 Step 2 (按格式聚合) 之后运行，按 LLM 识别的 feature_field
在原始日志行中提取值并统计分布，不区分格式。
"""

from __future__ import annotations

from collections import Counter, defaultdict

from agent.shared.logger import get_logger
from agent.tools.pipeline.log_feature_extractor import (
    _try_extract_json_feature,
    _try_extract_kv_feature,
)

logger = get_logger("log_parser_pipeline")


def aggregate_fields_by_type(
    lines_by_type: dict[str, list[str]],
    feature_field: str,
    format_info_map: dict[str, dict],
    log_format_map: dict[str, str],
) -> dict[str, Counter]:
    """
    按日志格式分组，对每种格式中的 feature_field 进行值分布统计。

    Args:
        lines_by_type: {"json": [...], "kv": [...], ...}
        feature_field: LLM 识别的特征字段（如 "event.action"）
        format_info_map: {"json": {"kv_connector": "=", ...}, ...}
        log_format_map: {"json": "JSON", "kv": "KV", ...}

    Returns:
        {"JSON": Counter({"login": 150, "logout": 30, ...}), ...}
    """
    result: dict[str, Counter] = {}
    for format_type, lines in lines_by_type.items():
        normalized = log_format_map.get(format_type, format_type.upper())
        counter: Counter = Counter()
        format_info = format_info_map.get(format_type, {})

        for line in lines[:200]:  # 最多采样 200 行
            try:
                if normalized == "JSON":
                    value = _try_extract_json_feature(line, feature_field)
                else:
                    value = _try_extract_kv_feature(
                        line, feature_field, format_type, format_info
                    )
                if value is not None:
                    counter[str(value)] += 1
            except Exception:
                pass

        result[normalized] = counter

    return result


def aggregate_all_fields(
    lines_by_type: dict[str, list[str]],
    feature_fields: list[str],
    format_info_map: dict[str, dict],
    log_format_map: dict[str, str],
) -> dict[str, dict[str, Counter]]:
    """
    多字段聚合：对多个 feature_field 同时进行分布统计。

    Args:
        lines_by_type: 按格式分组的日志行
        feature_fields: 多个特征字段列表
        format_info_map: 格式配置
        log_format_map: 格式归一化映射

    Returns:
        {field_name: {"JSON": Counter(...), "KV": Counter(...)}, ...}
    """
    result: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))

    for format_type, lines in lines_by_type.items():
        normalized = log_format_map.get(format_type, format_type.upper())
        format_info = format_info_map.get(format_type, {})

        for line in lines[:200]:
            for field in feature_fields:
                if not field:
                    continue
                try:
                    if normalized == "JSON":
                        value = _try_extract_json_feature(line, field)
                    else:
                        value = _try_extract_kv_feature(
                            line, field, format_type, format_info
                        )
                    if value is not None:
                        result[field][normalized][str(value)] += 1
                except Exception:
                    pass

    return {field: dict(counters) for field, counters in result.items()}


def build_field_summary(
    lines_by_type: dict[str, list[str]],
    feature_field: str,
    format_info_map: dict[str, dict],
    log_format_map: dict[str, str],
    top_n: int = 20,
) -> dict:
    """
    构建单字段的聚合摘要，包含总行数、提取率、Top-N 分布。

    Args:
        lines_by_type: 按格式分组的日志行
        feature_field: 特征字段
        format_info_map: 格式配置
        log_format_map: 格式归一化映射
        top_n: Top-N 分布数量

    Returns:
        {
            "feature_field": "event.action",
            "total_lines": 500,
            "extracted_lines": 480,
            "extraction_rate": 0.96,
            "top_values": [("login", 150), ("logout", 80), ...],
            "by_format": {"JSON": {...}, "KV": {...}},
        }
    """
    total_lines = sum(len(lines) for lines in lines_by_type.values())
    field_counts = aggregate_fields_by_type(
        lines_by_type, feature_field, format_info_map, log_format_map
    )

    # 合并所有格式的 Counter
    merged: Counter = Counter()
    for counter in field_counts.values():
        merged.update(counter)

    extracted_lines = sum(merged.values())

    return {
        "feature_field": feature_field,
        "total_lines": total_lines,
        "extracted_lines": extracted_lines,
        "extraction_rate": round(extracted_lines / total_lines, 3) if total_lines > 0 else 0.0,
        "top_values": merged.most_common(top_n),
        "by_format": {
            fmt: dict(counter.most_common(top_n))
            for fmt, counter in field_counts.items()
        },
    }