# -*- coding: utf-8 -*-
"""
统一的 LLM 响应后处理模块。

功能：
- LLM 响应的 JSON 解析与校验
- LLM 输出无效时的兜底 detail 构建
- 防御：裁剪多余 logtype、回填缺失 logtype
- 从原始日志中匹配真实样本行
"""

from __future__ import annotations

import json
from typing import Any

from agent.shared.logger import get_logger

logger = get_logger("log_parser_pipeline")


def _try_parse_json(text: str) -> dict | None:
    """鲁棒的 JSON 解析 —— 去除 markdown 围栏和尾随逗号。

    Args:
        text: LLM 原始响应字符串。

    Returns:
        解析后的字典，解析失败返回 None。
    """
    if not text or not text.strip():
        return None
    text = text.strip()
    # 去除 markdown 代码围栏
    if text.startswith("```"):
        # 去除开头围栏
        idx = text.find("\n")
        if idx != -1:
            text = text[idx + 1 :]
        # 去除结尾围栏
        if text.endswith("```"):
            text = text[:-3]
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 尝试去除最后一个 `]` 或 `}` 前的尾随逗号
        import re

        cleaned = re.sub(r",(\s*[}\]])", r"\1", text)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return None


def build_fallback_details(aggregation: dict) -> list[dict]:
    """从原始聚合数据构建兜底 classification_details。

    当 LLM 返回无效 JSON 时使用 —— 保留所有已知值及其首条样本行。

    Args:
        aggregation: ``aggregate_by_field`` 返回的字典。

    Returns:
        ``{"logtype": str, "sample": str}`` 字典列表。
    """
    details: list[dict] = []
    for val, info in aggregation.get("values", {}).items():
        details.append(
            {
                "logtype": val,
                "sample": info.get("samples", [None])[0] if info.get("samples") else "",
            }
        )
    return details


def sanitize_classification_details(
    parsed: dict,
    aggregation: dict,
) -> dict:
    """防御：对齐 classification_details 与实际聚合值。

    - 移除 LLM 臆造的 logtype（不在聚合结果中的）。
    - 回填 LLM 遗漏的 logtype（在聚合结果中但不在 LLM 输出中的）。

    Args:
        parsed:      解析后的 LLM 响应字典（原地修改）。
        aggregation: ``aggregate_by_field`` 返回的字典。

    Returns:
        同一个 ``parsed`` 字典（为方便链式调用而原地修改并返回）。
    """
    known_values: set[str] = set(aggregation.get("values", {}).keys())
    existing_logtypes: set[str] = {
        d.get("logtype") for d in parsed.get("classification_details", []) if d.get("logtype")
    }

    # 裁剪多余项
    extra_values = existing_logtypes - known_values
    if extra_values:
        logger.warning(f"[llm_postprocessor] Removing invented logtypes: {extra_values}")
        parsed["classification_details"] = [
            d
            for d in parsed.get("classification_details", [])
            if d.get("logtype") in known_values
        ]

    # 回填缺失项
    missing_values = known_values - existing_logtypes
    if missing_values:
        logger.warning(f"[llm_postprocessor] Backfilling missing logtypes: {missing_values}")
        for val in sorted(missing_values):
            info = aggregation["values"].get(val, {})
            samples = info.get("samples", [])
            sample = samples[0] if samples else ""
            parsed["classification_details"].append(
                {"logtype": val, "sample": sample}
            )

    parsed["feature_count"] = len(parsed.get("classification_details", []))
    return parsed


def match_real_samples(
    parsed: dict,
    logs_str: str,
    extractor_func,
    feature_field: str | None = None,
    header_end_marker: str = "",
) -> dict:
    """用真实原始日志行替换匿名化的样本行。

    对每个 classification detail，找到第一条特征字段值与 logtype 匹配的原始日志行，
    将 ``sample`` 和 ``real_samples`` 设为该原始行。

    CHANGED (2026-06-05): 新增对 KV 格式的支持，使用 feature_identifier 正则提取 body。

    Args:
        parsed:            解析后的 LLM 响应字典（原地修改）。
        logs_str:          原始多行日志字符串。
        extractor_func:    可调用对象 ``(line, feature_field) -> value``。
        feature_field:     字段名覆盖；回退使用 ``parsed["feature_field"]``。
        header_end_marker: 头部与 body 的分隔符。

    Returns:
        同一个 ``parsed`` 字典（为方便链式调用而原地修改并返回）。
    """
    ff = feature_field or parsed.get("feature_field", "log_type")
    log_lines = [l for l in logs_str.strip().split("\n") if l.strip()]
    details = parsed.get("classification_details", [])
    
    # CHANGED: 获取 feature_identifier 和 feature_body_group，用于 KV 格式 body 提取
    feature_identifier = parsed.get("feature_identifier", "")
    feature_body_group = parsed.get("feature_body_group", 0)
    has_feature_identifier = bool(feature_identifier and feature_body_group > 0)
    
    # CHANGED: 如果有 feature_identifier 正则，预编译
    import re as _re
    feature_pattern = None
    if has_feature_identifier:
        try:
            feature_pattern = _re.compile(feature_identifier)
            logger.info(
                f"[llm_postprocessor] 使用 feature_identifier 提取 body: "
                f"regex={feature_identifier[:50]}..., body_group={feature_body_group}"
            )
        except _re.error as e:
            logger.warning(f"[llm_postprocessor] feature_identifier 正则编译失败: {e}")

    sample_matched: dict[str, str] = {}
    for line in log_lines:
        if len(sample_matched) >= len(details):
            break
        body = line
        
        # CHANGED: 优先使用 feature_identifier 正则提取 body（KV 格式）
        if feature_pattern:
            match = feature_pattern.search(line)
            if match and len(match.groups()) >= feature_body_group:
                body = match.group(feature_body_group)
            else:
                # 正则匹配失败，降级使用 header_end_marker
                if header_end_marker:
                    parts = line.split(header_end_marker, 1)
                    if len(parts) == 2:
                        body = parts[1]
                else:
                    body = line
        elif header_end_marker:
            # 无 feature_identifier，JSON 格式：优先用 {...} 提取 body，
            # 避免 syslog 头多空格时 split(marker, 1) 从首个空格误切断
            from agent.tools.pipeline.common.json_utils import strip_header_to_body

            body = strip_header_to_body(line, header_end_marker, is_json=True)

        feature_val = extractor_func(body, ff)
        if feature_val is None and body != line:
            feature_val = extractor_func(line, ff)
        if feature_val is not None:
            val_str = str(feature_val)
            if val_str not in sample_matched:
                sample_matched[val_str] = line

    unmatched: list[str] = []
    for detail in details:
        lt = detail.get("logtype", "")
        matched_line = sample_matched.get(lt, "")
        detail["sample"] = matched_line
        
        # real_samples: 优先使用 feature_identifier 正则提取 body（KV 格式）
        if has_feature_identifier and feature_pattern and matched_line:
            match = feature_pattern.search(matched_line)
            if match and len(match.groups()) >= feature_body_group:
                detail["real_samples"] = match.group(feature_body_group)
                logger.info(
                    f"[llm_postprocessor] 为 '{lt}' "
                    f"使用正则提取 body ({len(detail['real_samples'])} 字符)"
                )
            else:
                # 正则匹配失败，降级使用 header_end_marker
                if header_end_marker:
                    parts = matched_line.split(header_end_marker, 1)
                    detail["real_samples"] = parts[1] if len(parts) == 2 else matched_line
                else:
                    detail["real_samples"] = matched_line
        elif header_end_marker and matched_line:
            # 无 feature_identifier，JSON 格式：优先用 {...} 提取 body，
            # 避免 syslog 头多空格时 split(marker, 1) 从首个空格误切断
            from agent.tools.pipeline.common.json_utils import strip_header_to_body

            detail["real_samples"] = strip_header_to_body(
                matched_line, header_end_marker, is_json=True
            )
        elif matched_line and "{" in matched_line:
            # fallback: header_end_marker 为空时，自动提取 JSON body
            json_start = matched_line.find("{")
            json_end = matched_line.rfind("}")
            if json_start != -1 and json_end > json_start:
                detail["real_samples"] = matched_line[json_start:json_end + 1]
            else:
                detail["real_samples"] = matched_line
        else:
            detail["real_samples"] = matched_line
        if not matched_line and lt:
            unmatched.append(lt)

    if sample_matched:
        logger.info(
            f"[llm_postprocessor] Sample matching: "
            f"{len(sample_matched)}/{len(details)} logtypes matched"
        )
    if unmatched:
        logger.warning(
            f"[llm_postprocessor] Unmatched logtypes: {unmatched[:10]}"
        )

    return parsed


def postprocess_llm_classification(
    llm_response: str,
    aggregation: dict,
    logs_str: str,
    extractor_func,
    feature_field: str | None = None,
    header_end_marker: str = "",
) -> dict:
    """完整的 LLM 响应后处理管线。

    1. 从 LLM 响应中解析 JSON。
    2. 若无效，从聚合数据构建兜底结果。
    3. 对照聚合值校验 classification_details。
    4. 从原始日志中匹配真实样本行。

    Args:
        llm_response:      LLM 原始响应字符串。
        aggregation:       ``aggregate_by_field`` 返回的字典。
        logs_str:          原始多行日志字符串。
        extractor_func:    可调用对象 ``(line, feature_field) -> value``。
        feature_field:     字段名覆盖。
        header_end_marker: 头部与 body 的分隔符。

    Returns:
        包含 status、classification_details、feature_count 等键的字典。
    """
    parsed = _try_parse_json(llm_response)

    if parsed is None:
        logger.warning("[llm_postprocessor] LLM returned invalid JSON, using fallback")
        return {
            "status": "PARTIAL",
            "classification_details": build_fallback_details(aggregation),
        }

    parsed.setdefault("status", "SUCCESS")
    parsed.setdefault("classification_details", [])

    parsed = sanitize_classification_details(parsed, aggregation)
    parsed = match_real_samples(
        parsed, logs_str, extractor_func,
        feature_field=feature_field,
        header_end_marker=header_end_marker,
    )

    return parsed