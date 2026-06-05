# -*- coding: utf-8 -*-
"""
日志头特征处理（Path A）。

当日志类型的分类特征位于日志头中时（Step 2a 判定 feature_location=header），
使用此模块处理：提取日志头 → 脱敏 → 聚合 → 调用专用 LLM → 替换样例日志。

CHANGED (2026-05-29): 集成 HeaderExtractor 消除重复代码；
                       增加 header_end_marker 传递和 real_samples 提取。
CHANGED (2026-06-02): 支持 KV 格式，feature_identifier 和 analysis 动态设置。
"""

from __future__ import annotations

import json
import re as _re

import httpx

from agent.core.prompts import load_log_header_classify_prompt, load_kv_feature_identifier_prompt
from agent.shared.logger import get_logger
from agent.tools.enum_extract_tool import sample_logs
from agent.tools.pipeline.extractors.header_extractor import aggregate_headers
from agent.tools.pipeline.llm_client import (
    _call_llm_direct,
    _try_parse_json,
    normalize_log_format,
)

logger = get_logger("log_parser_pipeline")

# JSON 格式的 feature_identifier 固定正则
_JSON_FEATURE_IDENTIFIER = r"(\{[\S\s]*\})"


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


def _parse_regex_response(response: str) -> str:
    """从 LLM 响应中鲁棒提取正则字符串。
    
    支持格式:
    - r'...' 或 r"..."
    - <regex>（纯字符串）
    - ```<regex>```（markdown 围栏）
    - 带解释文字的混合输出
    
    Returns:
        提取出的正则字符串，失败返回空字符串。
    """
    text = response.strip()
    
    # 尝试提取 r'...' 格式
    m = _re.search(r"r['\"](.+?)['\"]", text)
    if m:
        return m.group(1)
    
    # 尝试提取 markdown 代码块
    m = _re.search(r"```\w*\n?(.*?)\n?```", text, _re.DOTALL)
    if m:
        content = m.group(1).strip()
        # 可能带 r'...' 前缀
        inner = _re.search(r"r['\"](.+?)['\"]", content)
        if inner:
            return inner.group(1)
        return content
    
    # 兜底：去掉首尾引号
    text = text.strip("'\"")
    # 如果只有一行，直接返回
    if "\n" not in text and len(text) < 500:
        return text
    
    return ""


def _generate_kv_feature_identifier(logs_str: str) -> str:
    """用 LLM 生成 KV body 提取正则（单个捕获组，Group1 = KV body）。
    
    失败则抛出异常，不使用兜底策略。
    
    Returns:
        正则字符串，失败抛出 ValueError。
    """
    lines = [l.strip() for l in logs_str.strip().split("\n") if l.strip()]
    if not lines:
        raise ValueError("日志内容为空，无法生成 feature_identifier")
    
    sample_line = lines[0]
    
    # CHANGED: 使用 .replace() 替代 .format()，彻底避免花括号冲突（正则中的 \d{2} 等不会误解析）
    prompt = load_kv_feature_identifier_prompt().replace('{sample_log}', sample_line)
    try:
        response = _call_llm_direct(prompt, temperature=0.1, max_tokens=500, timeout=30)
    except Exception as e:
        raise ValueError(f"LLM API 调用失败: {e}")
    
    # 解析 LLM 输出
    regex_str = _parse_regex_response(response)
    if not regex_str:
        raise ValueError(f"LLM 输出无法解析为正则: {response[:200]}")
    
    # 验证：编译 + 匹配样例 + 确认恰好 1 个捕获组
    try:
        pattern = _re.compile(regex_str)
    except _re.error as e:
        raise ValueError(f"正则编译失败: {e}")
    
    m = pattern.search(sample_line)
    if not m:
        raise ValueError(f"正则无法匹配样例日志: {regex_str}")
    if len(m.groups()) != 1:
        raise ValueError(f"正则捕获组数≠1 (实际={len(m.groups())}): {regex_str}")
    
    logger.info(f"[_generate_kv_feature_identifier] 生成成功: {regex_str}")
    logger.info(f"[_generate_kv_feature_identifier] body 提取: {m.group(1)[:100]}...")
    return regex_str


def _replace_samples_with_raw(
    classification_data: dict,
    logs_str: str,
    header_end_marker: str = "",
) -> dict:
    """用 LLM 输出的 matched_regex 从原始日志中匹配真实样例。
    
    CHANGED (2026-06-05): 支持 KV 格式，使用 feature_identifier 正则提取 body。
    """
    log_lines = [l.strip() for l in logs_str.strip().split("\n") if l.strip()]
    
    # CHANGED: 获取 feature_identifier 和 feature_body_group，用于 KV 格式 body 提取
    feature_identifier = classification_data.get("feature_identifier", "")
    feature_body_group = classification_data.get("feature_body_group", 0)
    has_feature_identifier = bool(feature_identifier and feature_body_group > 0)
    
    # CHANGED: 如果有 feature_identifier 正则，预编译
    feature_pattern = None
    if has_feature_identifier:
        try:
            feature_pattern = _re.compile(feature_identifier)
            logger.info(
                f"[replace_samples] 使用 feature_identifier 提取 body: "
                f"regex={feature_identifier[:50]}..., body_group={feature_body_group}"
            )
        except _re.error as e:
            logger.warning(f"[replace_samples] feature_identifier 正则编译失败: {e}")

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
        
        # CHANGED: real_samples 提取逻辑，支持 KV 格式
        if has_feature_identifier and feature_pattern and found:
            # 优先使用 feature_identifier 正则提取 body（KV 格式）
            match = feature_pattern.search(found)
            if match and len(match.groups()) >= feature_body_group:
                detail["real_samples"] = match.group(feature_body_group)
                logger.info(
                    f"[replace_samples] 为 '{detail.get('logtype', '')}' "
                    f"使用正则提取 body ({len(detail['real_samples'])} 字符)"
                )
            else:
                # 正则匹配失败，降级使用 header_end_marker
                if header_end_marker:
                    parts = found.split(header_end_marker, 1)
                    detail["real_samples"] = parts[1] if len(parts) == 2 else found
                else:
                    detail["real_samples"] = found
        elif header_end_marker and found:
            # 无 feature_identifier，使用 header_end_marker 分割（JSON 格式）
            parts = found.split(header_end_marker, 1)
            detail["real_samples"] = parts[1] if len(parts) == 2 else found
        elif found and "{" in found:
            # fallback: header_end_marker 为空时，自动提取 JSON body
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
    CHANGED (2026-06-02): 根据 format_type 动态设置 feature_identifier 和 analysis。
    """
    # 辅助函数：根据 format_type 获取 feature_identifier
    def _get_feature_identifier(fmt_type: str) -> str:
        return "" if (fmt_type or "").lower() == "kv" else _JSON_FEATURE_IDENTIFIER

    if not logs_str or not logs_str.strip():
        return json.dumps(
            {"status": "FAILED", "error": "日志内容为空",
             "log_format": normalize_log_format(format_type),
             "log_format_detail": format_detail or format_type,
             "feature_field": "__header__", "feature_identifier": _get_feature_identifier(format_type),
             "feature_count": 0, "total_valid_lines": 0, "covered_lines": 0,
             "classification_details": []},
            ensure_ascii=False,
        )

    # CHANGED: KV 格式时，用 LLM 生成 feature_identifier
    is_kv = (format_type or "").lower() == "kv"
    kv_feature_identifier = ""
    if is_kv:
        try:
            kv_feature_identifier = _generate_kv_feature_identifier(logs_str)
        except ValueError as e:
            logger.error(f"[classify_header_features] KV feature_identifier 生成失败: {e}")
            return json.dumps(
                {"status": "FAILED", "error": f"KV feature_identifier 生成失败: {e}",
                 "log_format": normalize_log_format(format_type),
                 "log_format_detail": format_detail or format_type,
                 "feature_field": "__header__", "feature_identifier": "",
                 "feature_count": 0, "total_valid_lines": 0, "covered_lines": 0,
                 "classification_details": []},
                ensure_ascii=False,
            )

    try:
        agg_result = aggregate_headers(logs_str)
        clusters = agg_result["clusters"]
        total_lines = agg_result["total_lines"]

        if not clusters:
            logger.warning("[classify_header_features] 聚合结果为空")
            return json.dumps(
                {"status": "FAILED", "error": "日志头聚合结果为空",
                 "log_format": normalize_log_format(format_type),
                 "log_format_detail": format_detail or format_type,
                 "feature_field": "__header__", "feature_identifier": _get_feature_identifier(format_type),
                 "feature_count": 0, "total_valid_lines": total_lines,
                 "covered_lines": 0, "classification_details": []},
                ensure_ascii=False,
            )

        # CHANGED: 转义花括号，防止 str.format() 误解析
        aggregated_text = _escape_format_braces(json.dumps(clusters, ensure_ascii=False))
        sampled = _escape_format_braces(sample_logs(logs_str, 5))

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
                 "feature_field": "__header__", "feature_identifier": _get_feature_identifier(format_type),
                 "feature_count": 0, "total_valid_lines": total_lines,
                 "covered_lines": 0, "classification_details": [],
                 "raw_response": response[:500]},
                ensure_ascii=False,
            )

        # 后处理
        parsed["log_format"] = normalize_log_format(format_type)
        parsed.setdefault("log_format_detail", format_detail or format_type)
        parsed.setdefault("feature_field", "__header__")
        # CHANGED: KV 格式使用 LLM 生成的 feature_identifier，否则使用固定正则
        if is_kv and kv_feature_identifier:
            parsed["feature_identifier"] = kv_feature_identifier
            parsed["feature_body_group"] = 1
            parsed["feature_value_group"] = 0
        else:
            parsed["feature_identifier"] = _get_feature_identifier(format_type)
            parsed["feature_body_group"] = 0
            parsed["feature_value_group"] = 0
        parsed.setdefault("feature_count", 0)
        parsed.setdefault("total_valid_lines", total_lines)
        parsed.setdefault("covered_lines", sum(c["count"] for c in clusters[:20]))
        parsed.setdefault("classification_details", [])
        parsed.setdefault("categorical_features", "在日志头中")
        parsed.setdefault("Diversion_method", "日志头特征分类")
        # CHANGED: analysis 字段由 LLM 输出（delimit、tab），布尔值根据格式设置
        llm_analysis = parsed.get("analysis", {})
        parsed["analysis"] = {
            "has_json_structure": not is_kv,
            "has_cef_prefix": False,
            "has_key_value_pairs": is_kv,
            "has_delimited_structure": False,
            "delimit": llm_analysis.get("delimit", "判断失败"),
            "tab": llm_analysis.get("tab", "判断失败"),
        }
        # CHANGED: 使用传入的 header_end_marker 而非硬编码 ""
        parsed["header_end_marker"] = header_end_marker

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
             "feature_field": "__header__", "feature_identifier": _get_feature_identifier(format_type),
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
             "feature_field": "__header__", "feature_identifier": _get_feature_identifier(format_type),
             "feature_count": 0, "total_valid_lines": 0, "covered_lines": 0,
             "classification_details": []},
            ensure_ascii=False,
        )