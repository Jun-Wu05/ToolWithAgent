# -*- coding: utf-8 -*-
"""
日志头特征处理（Path A）。

当日志类型的分类特征位于日志头中时（Step 2a 判定 feature_location=header），
使用此模块处理：提取日志头 → 脱敏 → 聚合 → 调用专用 LLM → 替换样例日志。

CHANGED (2026-05-29): 集成 HeaderExtractor 消除重复代码；
                       增加 header_end_marker 传递和 real_samples 提取。
"""

from __future__ import annotations

import json
import re as _re

import httpx

from agent.core.prompts import load_log_header_classify_prompt
from agent.shared.logger import get_logger
from agent.tools.enum_extract_tool import sample_logs
from agent.tools.pipeline.extractors.header_extractor import aggregate_headers
from agent.tools.pipeline.llm_client import (
    _call_llm_direct,
    _try_parse_json,
    normalize_log_format,
)

logger = get_logger("log_parser_pipeline")

# Path A 仅处理格式 format=json 的 syslog+JSON 日志，固定单捕获组正则
_JSON_FEATURE_IDENTIFIER = r"(\{[\S\s]*\})"


def _replace_samples_with_raw(
    classification_data: dict,
    logs_str: str,
    header_end_marker: str = "",
) -> dict:
    """用 LLM 输出的 matched_regex 从原始日志中匹配真实样例。"""
    log_lines = [l.strip() for l in logs_str.strip().split("\n") if l.strip()]

    for detail in classification_data.get("classification_details", []):
        matched_regex = detail.get("matched_regex", "")
        if not matched_regex:
            detail["sample"] = ""
            detail["real_samples"] = ""
            continue

        try:
            pattern = _re.compile(matched_regex)
        except _re.error:
            logger.warning(f"[replace_samples] 正则语法错误: {matched_regex}")
            detail["sample"] = ""
            detail["real_samples"] = ""
            continue

        found = ""
        for line in log_lines:
            if pattern.search(line):
                found = line
                break

        # sample = 完整原始行
        detail["sample"] = found

        # real_samples: syslog+JSON 时仅保留 JSON body 部分
        if header_end_marker and found:
            parts = found.split(header_end_marker, 1)
            detail["real_samples"] = parts[1] if len(parts) == 2 else found
        elif found and "{" in found:
            json_start = found.find("{")
            json_end = found.rfind("}")
            if json_start != -1 and json_end > json_start:
                detail["real_samples"] = found[json_start:json_end + 1]
            else:
                detail["real_samples"] = found
        else:
            detail["real_samples"] = found

        if found:
            logger.info(
                f"[replace_samples] 为 '{detail.get('logtype', '')}' "
                f"匹配到样例 ({len(found)} 字符)"
            )

    return classification_data


def classify_header_features(
    logs_str: str,
    format_type: str = "json",
    format_detail: str = "",
    header_end_marker: str = "",
) -> str:
    """Path A: 日志头分类特征提取主函数。

    CHANGED: 新增 header_end_marker 参数，用于 real_samples 去头。
    """
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
        # CHANGED: 使用 HeaderExtractor.aggregate_headers() 替代重复实现
        agg_result = aggregate_headers(logs_str)
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
        # CHANGED: 强制覆盖为统一正则，防止 LLM 输出不一致
        parsed["feature_identifier"] = _JSON_FEATURE_IDENTIFIER
        parsed.setdefault("feature_count", 0)
        parsed.setdefault("total_valid_lines", total_lines)
        parsed.setdefault("covered_lines", sum(c["count"] for c in clusters[:20]))
        parsed.setdefault("classification_details", [])
        parsed.setdefault("categorical_features", "在日志头中")
        parsed.setdefault("Diversion_method", "日志头特征分类")
        parsed["analysis"] = {
            "has_json_structure": True, "has_cef_prefix": False,
            "has_key_value_pairs": False, "has_delimited_structure": False,
            "delimit": ":", "tab": "space",
        }
        # CHANGED: 使用传入的 header_end_marker 而非硬编码 ""
        parsed["header_end_marker"] = header_end_marker
        parsed["feature_body_group"] = 0
        parsed["feature_value_group"] = 0

        if parsed.get("status") == "SUCCESS":
            # CHANGED: 传入 header_end_marker 以提取 real_samples
            parsed = _replace_samples_with_raw(parsed, logs_str, header_end_marker)
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