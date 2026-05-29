# -*- coding: utf-8 -*-
"""
日志头特征处理（Path A）。

当日志类型的分类特征位于日志头中时（has_header_feature=true），
使用此模块处理：提取日志头 -> 脱敏 -> 聚合 -> 调用专用 LLM -> 替换样例日志。
"""

from __future__ import annotations

import json
import re as _re
from collections import Counter, defaultdict
from typing import Any

import httpx

from agent.core.prompts import load_log_header_classify_prompt
from agent.shared.logger import get_logger
from agent.tools.enum_extract_tool import sample_logs
from agent.tools.pipeline.llm_client import (
    _call_llm_direct,
    _try_parse_json,
    normalize_log_format,
)

logger = get_logger("log_parser_pipeline")


_HEADER_DESENSITIZE_RE = _re.compile(
    r'<\d+>|'
    r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?|'
    r'[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}|'
    r'\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2}|'
    r'\d{1,3}(\.\d{1,3}){3}|'
    r'([0-9a-fA-F]{1,4}:){1,7}[0-9a-fA-F]{1,4}|::|'
    r'([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})|'
    r'[0-9A-Fa-f]{8}-([0-9A-Fa-f]{4}-){3}[0-9A-Fa-f]{12}|'
    r'[a-zA-Z0-9]{15,}|'
    r'\b\d+\b|'
    r'host|server|pid|ppid|uid|gid|sessionid|messageid',
    _re.IGNORECASE,
)

# Path A 仅处理格式 format=json 的 syslog+JSON 日志，固定双捕获组正则
_JSON_FEATURE_IDENTIFIER = r"(\{[\S\s]*\})"


def _extract_header(line: str) -> str:
    """从日志行中提取日志头部分（{ 之前的文本）。"""
    json_start = line.find("{")
    if json_start == -1:
        json_start = line.find("[")
    if json_start > 0:
        return line[:json_start].strip()
    return line.strip()


def _desensitize_header(header: str) -> str:
    """脱敏日志头，将 IP/时间/UUID 等替换为 '1'。"""
    desensitized = _HEADER_DESENSITIZE_RE.sub("1", header)
    desensitized = _re.sub(r'\s+', ' ', desensitized).strip()
    return desensitized


def _aggregate_headers(logs_str: str, max_clusters: int = 50) -> dict:
    """提取日志头、脱敏、聚合。"""
    lines = [l for l in logs_str.strip().split("\n") if l.strip()]
    total_lines = len(lines)

    cluster_map: dict[str, int] = defaultdict(int)
    header_samples: dict[str, str] = {}

    for line in lines:
        if len(cluster_map) >= max_clusters:
            break

        header = _extract_header(line)
        if not header:
            continue

        desensitized = _desensitize_header(header)
        if not desensitized:
            continue

        cluster_map[desensitized] += 1
        if desensitized not in header_samples:
            sample = desensitized[:3000]
            if len(desensitized) > 3000:
                sample += "...日志过长已截断"
            header_samples[desensitized] = sample

    sorted_clusters = sorted(cluster_map.items(), key=lambda x: x[1], reverse=True)
    clusters = [
        {"log_header": header_samples[header], "count": count}
        for header, count in sorted_clusters
    ]

    return {"clusters": clusters, "total_lines": total_lines}


def _replace_samples_with_raw(classification_data: dict, logs_str: str) -> dict:
    """用 LLM 输出的 matched_regex 从原始日志中匹配真实样例。"""
    log_lines = [l.strip() for l in logs_str.strip().split("\n") if l.strip()]

    for detail in classification_data.get("classification_details", []):
        matched_regex = detail.get("matched_regex", "")
        if not matched_regex:
            detail["sample"] = ""
            continue

        try:
            pattern = _re.compile(matched_regex)
        except _re.error:
            logger.warning(f"[replace_samples] 正则语法错误: {matched_regex}")
            detail["sample"] = ""
            continue

        found = ""
        for line in log_lines:
            if pattern.search(line):
                found = line
                break

        detail["sample"] = found
        if found:
            logger.info(
                f"[replace_samples] 为 '{detail.get('value', '')}' "
                f"匹配到样例 ({len(found)} 字符)"
            )

    return classification_data


def classify_header_features(
    logs_str: str,
    format_type: str = "json",
    format_detail: str = "",
) -> str:
    """Path A: 日志头分类特征提取主函数。"""
    if not logs_str or not logs_str.strip():
        return json.dumps(
            {"status": "FAILED", "error": "日志内容为空",
             "log_format": normalize_log_format(format_type),
             "log_format_detail": format_detail or format_type,
             "feature_field": "__header__", "feature_identifier": _JSON_FEATURE_IDENTIFIER,
             "feature_count": 0, "total_valid_lines": 0, "covered_lines": 0,
             "classification_details": []},
            ensure_ascii=False,
        )

    try:
        agg_result = _aggregate_headers(logs_str)
        clusters = agg_result["clusters"]
        total_lines = agg_result["total_lines"]

        if not clusters:
            logger.warning("[classify_header_features] 聚合结果为空")
            return json.dumps(
                {"status": "FAILED", "error": "日志头聚合结果为空",
                 "log_format": normalize_log_format(format_type),
                 "log_format_detail": format_detail or format_type,
                 "feature_field": "__header__", "feature_identifier": _JSON_FEATURE_IDENTIFIER,
                 "feature_count": 0, "total_valid_lines": total_lines,
                 "covered_lines": 0, "classification_details": []},
                ensure_ascii=False,
            )

        aggregated_text = json.dumps(clusters, ensure_ascii=False)
        sampled = sample_logs(logs_str, 5)

        prompt = load_log_header_classify_prompt().format(
            aggregated_headers=aggregated_text,
            sample_count="5",
            sampled_logs=sampled,
        )

        logger.info(
            f"[classify_header_features] 调用 LLM, "
            f"clusters={len(clusters)}, prompt_len={len(prompt)}"
        )

        response = _call_llm_direct(
            prompt, temperature=0.1, max_tokens=4000, timeout=90
        )

        parsed = _try_parse_json(response)
        if parsed is None:
            logger.warning(f"[classify_header_features] LLM 返回非 JSON: {response[:200]}")
            return json.dumps(
                {"status": "FAILED", "error": "LLM 返回非 JSON",
                 "log_format": normalize_log_format(format_type),
                 "log_format_detail": format_detail or format_type,
                 "feature_field": "__header__", "feature_identifier": _JSON_FEATURE_IDENTIFIER,
                 "feature_count": 0, "total_valid_lines": total_lines,
                 "covered_lines": 0, "classification_details": [],
                 "raw_response": response[:500]},
                ensure_ascii=False,
            )

        # 后处理
        parsed["log_format"] = normalize_log_format(format_type)
        parsed.setdefault("log_format_detail", format_detail or format_type)
        parsed.setdefault("feature_field", "__header__")
        parsed.setdefault("feature_identifier", _JSON_FEATURE_IDENTIFIER)
        parsed.setdefault("feature_count", 0)
        parsed.setdefault("total_valid_lines", total_lines)
        parsed.setdefault("covered_lines", sum(c["count"] for c in clusters[:20]))
        parsed.setdefault("classification_details", [])
        parsed.setdefault("categorical_features", "在日志头中")
        parsed.setdefault("Diversion_method", "数据匹配再解析")
        parsed["analysis"] = {
            "has_json_structure": True, "has_cef_prefix": False,
            "has_key_value_pairs": False, "has_delimited_structure": False,
            "delimit": ":", "tab": "space",
        }
        parsed["header_end_marker"] = ""
        parsed["feature_body_group"] = 0
        parsed["feature_value_group"] = 0

        if parsed.get("status") == "SUCCESS":
            parsed = _replace_samples_with_raw(parsed, logs_str)
            parsed["feature_count"] = len(parsed.get("classification_details", []))

            try:
                from agent.tools.log_pattern_store import (
                    generate_structured_fingerprint, store_log_knowledge,
                )
                structured_fp = generate_structured_fingerprint(
                    classify_result=parsed, format_detail=format_detail,
                    feature_field="__header__",
                )
                if structured_fp:
                    _sl = [l for l in logs_str.strip().split("\n") if l.strip()][:10]
                    store_log_knowledge(
                        fingerprint=structured_fp, format_type=format_type,
                        meta=parsed, sample_logs=_sl,
                    )
                    logger.info(f"[classify_header_features] 知识库存储成功: {structured_fp[:80]}...")
            except Exception as store_err:
                logger.warning(f"[classify_header_features] 知识库存储失败: {store_err}")
        else:
            parsed.setdefault("fail_reason", "LLM 判断分类失败")

        return json.dumps(parsed, ensure_ascii=False)

    except httpx.HTTPStatusError as e:
        logger.error(f"[classify_header_features] API 错误: {e}")
        return json.dumps(
            {"status": "FAILED", "error": f"LLM API 调用失败: {e.response.status_code}",
             "log_format": normalize_log_format(format_type),
             "log_format_detail": format_detail or format_type,
             "feature_field": "__header__", "feature_identifier": _JSON_FEATURE_IDENTIFIER,
             "feature_count": 0, "total_valid_lines": 0, "covered_lines": 0,
             "classification_details": []},
            ensure_ascii=False,
        )
    except Exception as e:
        logger.error(f"[classify_header_features] 异常: {type(e).__name__}: {e}")
        return json.dumps(
            {"status": "FAILED", "error": str(e),
             "log_format": normalize_log_format(format_type),
             "log_format_detail": format_detail or format_type,
             "feature_field": "__header__", "feature_identifier": _JSON_FEATURE_IDENTIFIER,
             "feature_count": 0, "total_valid_lines": 0, "covered_lines": 0,
             "classification_details": []},
            ensure_ascii=False,
        )