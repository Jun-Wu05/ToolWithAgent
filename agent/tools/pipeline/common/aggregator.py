# -*- coding: utf-8 -*-
"""
统一的日志特征值聚合模块。

按特征字段值对日志行分组，统计出现次数，
并采集样本行（每个值最多 3 条）。
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Callable

from agent.shared.logger import get_logger

logger = get_logger("log_parser_pipeline")

# 类型别名：可调用对象 (line: str, feature_field: str) → value 或 None
_ExtractorFunc = Callable[[str, str], Any]


def aggregate_by_field(
    logs_str: str,
    feature_field: str,
    extractor: _ExtractorFunc,
    max_lines: int = 2000,
    sample_limit: int = 3,
    sample_max_chars: int = 300,
    kv_delimit: str | None = None,
    field_delimit: str | None = None,
    header_end_marker: str = "",
    is_json: bool = True,
) -> dict:
    """使用可插拔的提取器按特征字段值对日志行分组。

    这是聚合的唯一真相源 —— 所有提取器策略（JSON、KV、Header）共用。

    Args:
        logs_str:         原始多行日志字符串。
        feature_field:    要聚合的字段名。
        extractor:        可调用对象 ``(line, feature_field) → value``。
        max_lines:        最大处理行数。
        sample_limit:     每个值保留的最大样本行数。
        sample_max_chars: 每条样本行的最大字符数（超出截断）。
        kv_delimit:       KV 格式的键值分隔符（可选）。
        field_delimit:    KV 格式的字段分隔符（可选）。
        header_end_marker: 日志头与 body 的分隔符（用于剥离日志头）。
        is_json:          是否按 JSON 格式剥离头部。JSON 优先用 ``{...}``
                          提取 body，避免 syslog 头多空格误切断；
                          KV/其他格式保持原 ``split(marker, 1)`` 行为。

    Returns:
        {
            "total_lines": int,
            "matched_lines": int,
            "feature_field": str,
            "values": {value: {"count": int, "samples": [str, ...]}, ...},
            "value_count": int,
            "top_values": [str, ...],
        }
    """
    # CHANGED: 使用 header_end_marker 剥离日志头（2026-06-08 修复 syslog 头部干扰问题）
    # CHANGED: JSON 格式优先用 {...} 提取 body，避免 syslog 头多空格误切断（2026-06-29）
    from agent.tools.pipeline.common.json_utils import strip_header_to_body

    lines = []
    for line in logs_str.strip().split("\n"):
        if not line.strip():
            continue
        stripped_line = strip_header_to_body(
            line, header_end_marker, is_json=is_json
        ).strip()
        lines.append(stripped_line)
    
    lines = lines[:max_lines]
    total_lines = len(lines)
    matched_lines = 0

    value_counter: Counter[str] = Counter()
    value_samples: dict[str, list[str]] = {}
    unmatched_samples: list[str] = []

    # CHANGED: 添加日志，显示是否剥离了日志头
    if header_end_marker:
        logger.info(
            f"[aggregator] 使用 header_end_marker='{header_end_marker}' 剥离日志头"
        )

    for line in lines:
        feature_value = extractor(line, feature_field)
        if feature_value is None:
            # 未匹配行不归入任何类型；保留少量样本供覆盖信息展示。
            if len(unmatched_samples) < sample_limit:
                sample = line[:sample_max_chars].strip()
                if sample not in unmatched_samples:
                    unmatched_samples.append(sample)
            continue

        matched_lines += 1
        feature_str = str(feature_value)
        value_counter[feature_str] += 1

        if feature_str not in value_samples:
            value_samples[feature_str] = []
        if len(value_samples[feature_str]) < sample_limit:
            sample = line[:sample_max_chars].strip()
            if sample not in value_samples[feature_str]:
                value_samples[feature_str].append(sample)

    values_dict: dict[str, dict] = {}
    for val, cnt in value_counter.most_common():
        values_dict[val] = {
            "count": cnt,
            "samples": value_samples.get(val, []),
        }

    # CHANGED: 增强日志输出，显示聚合结果和分隔符信息（2026-06-08 修复）
    kv_delimit_str = kv_delimit if kv_delimit is not None else "unknown"
    field_delimit_str = field_delimit if field_delimit is not None else "unknown"
    logger.info(
        f"[aggregator] Aggregation complete: "
        f"total={total_lines}, matched={matched_lines}, "
        f"unique_values={len(value_counter)}, field='{feature_field}', "
        f"kv_delimit='{kv_delimit_str}', "
        f"field_delimit='{field_delimit_str}'"
    )

    return {
        "total_lines": total_lines,
        "matched_lines": matched_lines,
        "unmatched_lines": total_lines - matched_lines,
        "unmatched_samples": unmatched_samples,
        "feature_field": feature_field,
        "values": values_dict,
        "value_count": len(value_counter),
        "top_values": [v for v, _ in value_counter.most_common(20)],
    }