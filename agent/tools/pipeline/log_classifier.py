# -*- coding: utf-8 -*-
"""
Step 2 — 日志特征分类器。

将日志分类路由到相应的提取器策略，
调用 LLM 进行语义分组，并对结果进行后处理。

路由逻辑（CHANGED 2026-06-02）：
- 日志头+JSON 格式 → Step 2a 特征定位 → Path A (header) / Path Main (body)
- 纯 JSON 格式 → 直接 Path Main
- 日志头+KV 格式 → Step 2a 特征定位 → Path A (header) / Path KV (body)
- 纯 KV 格式 → 直接 Path KV
- 其他格式 → UNSUPPORTED
"""

from __future__ import annotations

import json
import re as _re_mod

import httpx
from agno.tools import tool

from agent.prompts import load_log_classify_feature_prompt as load_log_classify_prompt
from agent.shared.logger import get_logger
from agent.tools.enum_extract_tool import sample_logs
from agent.tools.pipeline.llm_client import (
    _call_llm_direct,
    normalize_log_format,
)
from agent.tools.pipeline.classification_policy import (
    BODY_KEY_COVERAGE_THRESHOLD,
    decide_body_key_route,
)
from agent.tools.pipeline.common.format_context import FormatContext

logger = get_logger("log_parser_pipeline")


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _build_failed_result(
    format_type: str,
    format_detail: str,
    feature_field: str,
    error: str,
    total_valid_lines: int = 0,
) -> str:
    """构造并返回 JSON 编码的 FAILED 结果字典。"""
    return json.dumps(
        {
            "status": "FAILED",
            "error": error,
            "log_format": normalize_log_format(format_type),
            "log_format_detail": format_detail or format_type,
            "feature_field": feature_field,
            "feature_identifier": _build_feature_identifier(format_type, format_detail),
            "feature_count": 0,
            "total_valid_lines": total_valid_lines,
            "covered_lines": 0,
            "classification_details": [],
        },
        ensure_ascii=False,
    )


def _build_feature_identifier(format_type: str, format_detail: str) -> str:
    """为 JSON 类格式生成固定的双捕获组正则。

    Group1 捕获 JSON body（从第一个 { 到最后一个 }），
    Group2 捕获特征值（后续由 log_sample_filler 按 logtype 匹配）。

    仅当 format_type 或 format_detail 中包含 "json" 时才返回正则；
    否则返回空字符串。
    """
    fmt_lower = (format_type + " " + (format_detail or "")).lower()
    if "json" in fmt_lower:
        return r"(\{[\S\s]*\})"
    return ""


def _meaning_fill_batches(
    aggregation: dict,
    logs_str: str,
    *,
    format_type: str,
    format_detail: str,
    feature_field: str,
    header_end_marker: str = "",
    sample_format: str = "",
    extractor_func=None,
    feature_identifier: str = "",
    feature_body_group: int = 0,
    batch_size: int = 20,
) -> dict:
    """分批（≤batch_size 值/批）调用分类 LLM 补充 meaning 并合并（#190）。

    类型集合始终以聚合值为准（sanitize 裁剪臆造、回填遗漏）；批次返回
    无效 JSON 时该批回退聚合详情并把状态降为 PARTIAL；API 异常向上抛出，
    由调用方按既有语义处理。

    Returns:
        {"classification_details": [...], "status": "SUCCESS"|"PARTIAL",
         "feature_count": int}
    """
    from agent.tools.pipeline.common.llm_postprocessor import (
        postprocess_llm_classification,
    )

    all_values = list(aggregation.get("values", {}).keys())
    format_name = normalize_log_format(format_type) or format_type
    sampled_logs_str = sample_logs(logs_str, 5)

    details: list[dict] = []
    status = "SUCCESS"
    fail_reasons: list[str] = []
    for start in range(0, len(all_values), batch_size):
        batch_values = all_values[start:start + batch_size]
        batch_values_detail = {}
        for val in batch_values:
            info = aggregation["values"].get(val, {})
            batch_values_detail[val] = {
                "count": info.get("count", 0),
                "samples": info.get("samples", []),
            }
        prompt = load_log_classify_prompt().format(
            format_type=format_name,
            format_detail=format_detail,
            feature_field=feature_field,
            aggregation_text=json.dumps(batch_values_detail, ensure_ascii=False),
            sampled_logs=sampled_logs_str,
        )
        logger.info(
            f"[meaning_fill] 批次 {start // batch_size + 1}: "
            f"values={len(batch_values)}/{len(all_values)}, prompt_len={len(prompt)}"
        )
        batch_aggregation = {
            **aggregation,
            "values": {v: aggregation["values"].get(v, {}) for v in batch_values},
            "top_values": batch_values,
        }
        response = _call_llm_direct(
            prompt, temperature=0.2, max_tokens=8000, timeout=120
        )
        parsed = postprocess_llm_classification(
            response, batch_aggregation, logs_str,
            extractor_func=extractor_func,
            feature_field=feature_field,
            header_end_marker=header_end_marker,
            sample_format=sample_format,
            feature_identifier=feature_identifier,
            feature_body_group=feature_body_group,
        )
        details.extend(parsed.get("classification_details", []))
        if parsed.get("status") != "SUCCESS":
            status = "PARTIAL"
            if parsed.get("fail_reason"):
                fail_reasons.append(str(parsed["fail_reason"]))

    return {
        "classification_details": details,
        "status": status,
        "feature_count": len(details),
        "fail_reason": "; ".join(dict.fromkeys(fail_reasons)),
    }


# ---------------------------------------------------------------------------
# 核心：统一的 JSON 分类（替代旧 Path B + C）
# ---------------------------------------------------------------------------

def _classify_json_features(
    logs_str: str,
    format_type: str,
    format_detail: str,
    feature_field: str,
    header_end_marker: str = "",
) -> str:
    """统一的 JSON body 特征分类。

    使用 :class:`extractors.JsonExtractor` 提取值，
    :mod:`common.aggregator` 分组，LLM 语义分组，
    :mod:`common.llm_postprocessor` 清洗。
    """
    from agent.tools.pipeline.extractors.json_extractor import JsonExtractor

    # 0. 校验输入
    if not logs_str or not logs_str.strip():
        return _build_failed_result(format_type, format_detail, feature_field, "日志内容为空")

    if not feature_field or not feature_field.strip():
        return _build_failed_result(format_type, format_detail, feature_field, "feature_field 为空，Step1 未识别出分类字段")

    # 1. 使用 JsonExtractor 提取 + 聚合
    extractor = JsonExtractor()
    aggregation = extractor.extract_and_aggregate(logs_str, feature_field)

    total_lines = aggregation.get("total_lines", 0)
    matched_lines = aggregation.get("matched_lines", 0)

    if matched_lines == 0:
        logger.warning(
            f"[_classify_json_features] 未匹配到任何 feature_field='{feature_field}' 的日志行"
        )
        return json.dumps(
            {
                "status": "FAILED",
                "error": f"未找到字段 '{feature_field}' 的有效值",
                "log_format": normalize_log_format(format_type),
                "log_format_detail": format_detail or format_type,
                "feature_field": feature_field,
                "feature_identifier": _build_feature_identifier(format_type, format_detail),
                "feature_count": aggregation.get("value_count", 0),
                "total_valid_lines": total_lines,
                "covered_lines": 0,
                "classification_details": [
                    {"logtype": val, "count": info.get("count", 0), "sample": (info.get("samples", [""]) or [""])[0]}
                    for val, info in aggregation.get("values", {}).items()
                ],
            },
            ensure_ascii=False,
        )

    # 2-5. 分批（≤20 值/批）调用分类 LLM 并后处理（#190：不再只取前 20 个值）
    try:
        parsed = _meaning_fill_batches(
            aggregation, logs_str,
            format_type=format_type,
            format_detail=format_detail or format_type,
            feature_field=feature_field,
            header_end_marker=header_end_marker,
            sample_format="json",
            extractor_func=extractor.extract_value,
        )
    except httpx.HTTPStatusError as e:
        logger.error(f"[_classify_json_features] API error: {e}")
        return _build_failed_result(format_type, format_detail, feature_field, f"LLM API 调用失败: {e.response.status_code}")
    except Exception as e:
        logger.error(f"[_classify_json_features] LLM error: {type(e).__name__}: {e}")
        return _build_failed_result(format_type, format_detail, feature_field, str(e), total_valid_lines=total_lines)

    # 6. 填充元数据字段
    format_name = normalize_log_format(format_type) or format_type
    result = {
        "status": parsed.get("status", "PARTIAL"),
        "log_format": format_name,
        "log_format_detail": format_detail or format_type,
        "feature_field": feature_field,
        "feature_identifier": _build_feature_identifier(format_type, format_detail),
        "feature_count": parsed.get("feature_count", len(parsed.get("classification_details", []))),
        "total_valid_lines": total_lines,
        "covered_lines": matched_lines,
        "coverage": _build_coverage_block(aggregation),
        "classification_details": parsed.get("classification_details", []),
        # CHANGED: 添加 JSON 格式的 analysis 字段
        "analysis": {
            "has_json_structure": True,
            "has_cef_prefix": False,
            "has_key_value_pairs": False,
            "has_delimited_structure": False,
            "delimit": "",
            "tab": "",
        },
        "categorical_features": feature_field,
        "Diversion_method": "日志类型",
        "fail_reason": "",
        "feature_body_group": 0,
        "feature_value_group": 0,
    }

    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 核心：统一的 KV 分类
# ---------------------------------------------------------------------------

def _classify_kv_features(
    logs_str: str,
    format_type: str,
    format_detail: str,
    feature_field: str,
    format_info: dict | None,
    header_end_marker: str = "",
) -> str:
    """统一的 KV body 特征分类。

    使用 :class:`extractors.KvExtractor` 提取值，
    :mod:`common.aggregator` 分组，LLM 语义分组，
    :mod:`common.llm_postprocessor` 清洗。
    """
    from agent.tools.pipeline.extractors.kv_extractor import KvExtractor

    # 0. 校验输入
    if not logs_str or not logs_str.strip():
        return _build_failed_result(format_type, format_detail, feature_field, "日志内容为空")

    if not feature_field or not feature_field.strip():
        return _build_failed_result(format_type, format_detail, feature_field, "feature_field 为空，Step1 未识别出分类字段")

    # 1. 解析分隔符上下文（delimit=字段分隔符，tab=键值分隔符，#344 单一解析）；
    # format_info 为 None 时无条件回退默认分隔符，body_logs 先按原文初始化（#179）
    field_delimit, kv_delimit = FormatContext.from_format_info(format_info)
    body_logs = logs_str
    if format_info and header_end_marker:
        # 改用 strip_header_to_body 从左 split(marker, 1)（修复 issue #14），
        # 与全仓其它 8 处剥头一致。原 rpartition 从右切，当 header_end_marker 与 KV 字段
        # 分隔符相同（如 skyeye_ioc 日志 marker='\t' 且字段也用 \t 分隔）时，只保留每行
        # 最后一个字段，type= 等字段被切进 header 丢失，导致 matched=0。
        from agent.tools.pipeline.common.json_utils import strip_header_to_body
        lines = logs_str.strip().split('\n')
        body_lines = []
        extracted_count = 0
        for line in lines:
            body = strip_header_to_body(line, header_end_marker, is_json=False)
            stripped_body = body.strip()
            if stripped_body and stripped_body != line.strip():
                # 成功剥离头部，body 非空且与原行不同
                body_lines.append(stripped_body)
                extracted_count += 1
            elif stripped_body:
                # marker 未匹配到（strip_header_to_body 返回原行），保留原始行（兼容性）
                body_lines.append(line)
            else:
                # 日志体为空，保留原始行（兼容性）
                body_lines.append(line)
                logger.warning(
                    "[_classify_kv_features] 日志体为空，保留原始行; "
                    f"line_length={len(line)}"
                )
        body_logs = '\n'.join(body_lines)

        # 确定性回退（PR #121 修复）：剥离使特征键行存在率大幅下降 → marker 无效。
        # 典型：幻觉 marker 等于字段分隔符，把行首第一个字段（常为特征字段）剥掉。
        probe = KvExtractor(field_delimit=field_delimit, kv_delimit=kv_delimit)
        before_hits = sum(
            1 for line in lines if probe.extract_value(line, feature_field) is not None
        )
        after_hits = sum(
            1 for line in body_lines if probe.extract_value(line, feature_field) is not None
        )
        if before_hits > 0 and after_hits < before_hits * 0.5:
            logger.warning(
                f"[_classify_kv_features] header_end_marker='{header_end_marker}' 剥离使特征键 "
                f"'{feature_field}' 行存在率 {before_hits}->{after_hits}，判定 marker 无效，回退不剥离"
            )
            body_lines = lines
            body_logs = logs_str
            header_end_marker = ""

        logger.info(
            "[_classify_kv_features] header_end_marker 提取日志体完成: "
            f"marker_length={len(header_end_marker)}, "
            f"成功={extracted_count}/{len(lines)}, body_length={len(body_logs)}"
        )

    # 2. 使用 KvExtractor 提取 + 聚合（使用新参数名）
    extractor = KvExtractor(field_delimit=field_delimit, kv_delimit=kv_delimit)
    aggregation = extractor.extract_and_aggregate(body_logs, feature_field)

    total_lines = aggregation.get("total_lines", 0)
    matched_lines = aggregation.get("matched_lines", 0)

    # 空格字段分隔符 + 声称键值分隔符零匹配时，对称重试另一种键值分隔符
    # （进入 "=" 试 ":"，进入 ":" 试 "="；仅成功时更新 kv_delimit，供 analysis 回显与后续裁决）。
    if matched_lines == 0 and field_delimit == " " and kv_delimit in ("=", ":"):
        alternative = ":" if kv_delimit == "=" else "="
        logger.warning(
            f"[_classify_kv_features] 声称键值分隔符 {kv_delimit!r} 零匹配，尝试备选分隔符 {alternative!r}"
        )
        extractor = KvExtractor(field_delimit=field_delimit, kv_delimit=alternative)
        aggregation = extractor.extract_and_aggregate(body_logs, feature_field)
        matched_lines = aggregation.get("matched_lines", 0)
        if matched_lines > 0:
            kv_delimit = alternative
            logger.info(
                f"[_classify_kv_features] 备选分隔符 {alternative!r} 成功，匹配到 {matched_lines} 行"
            )

    if matched_lines == 0:
        # 数据裁决兜底（#259）："LLM 提议、数据裁决"——声称分隔符零匹配时，
        # 对候选集（声称值 + LLM 原样 delimiter + 常见符号 + 数据派生）逐个用
        # 特征键行覆盖率探针打分，取最高且达阈值者重试聚合；全不达阈值才失败。
        candidates: list[str] = []
        raw_delimiter = (format_info or {}).get("delimiter")
        for candidate in (
            field_delimit,
            raw_delimiter,
            "||",
            "|",
            ";",
            ",",
            "\t",
            "space",
            *_derive_separator_candidates(body_logs),
        ):
            if candidate and candidate not in candidates:
                candidates.append(candidate)
        best_delimit = None
        best_coverage = 0.0
        for candidate in candidates:
            coverage = _kv_key_line_coverage(
                body_logs, feature_field, FormatContext(candidate, kv_delimit)
            )
            if coverage > best_coverage:
                best_delimit, best_coverage = candidate, coverage
        if best_delimit is not None and best_coverage >= BODY_KEY_COVERAGE_THRESHOLD:
            logger.warning(
                f"[_classify_kv_features] 声称分隔符 '{field_delimit}' 零匹配，"
                f"探针裁决改用 '{best_delimit}'（特征键行覆盖率 {best_coverage:.0%}）重试聚合"
            )
            field_delimit = best_delimit
            extractor = KvExtractor(field_delimit=field_delimit, kv_delimit=kv_delimit)
            aggregation = extractor.extract_and_aggregate(body_logs, feature_field)
            total_lines = aggregation.get("total_lines", total_lines)
            matched_lines = aggregation.get("matched_lines", 0)

    if matched_lines == 0:
        logger.warning(
            f"[_classify_kv_features] 未匹配到任何 feature_field='{feature_field}' 的日志行"
        )
        return json.dumps(
            {
                "status": "FAILED",
                "error": f"未找到字段 '{feature_field}' 的有效值",
                "log_format": normalize_log_format(format_type),
                "log_format_detail": format_detail or format_type,
                "feature_field": feature_field,
                "feature_identifier": _build_feature_identifier(format_type, format_detail),
                "feature_count": aggregation.get("value_count", 0),
                "total_valid_lines": total_lines,
                "covered_lines": 0,
                "classification_details": [
                    {"logtype": val, "count": info.get("count", 0), "sample": (info.get("samples", [""]) or [""])[0]}
                    for val, info in aggregation.get("values", {}).items()
                ],
            },
            ensure_ascii=False,
        )

    # 2-5. 分批（≤20 值/批）调用分类 LLM 并后处理（#190：不再只取前 20 个值）
    try:
        parsed = _meaning_fill_batches(
            aggregation, logs_str,
            format_type=format_type,
            format_detail=format_detail or format_type,
            feature_field=feature_field,
            header_end_marker=header_end_marker,
            sample_format="kv",
            extractor_func=extractor.extract_value,
        )
    except httpx.HTTPStatusError as e:
        logger.error(f"[_classify_kv_features] API error: {e}")
        return _build_failed_result(format_type, format_detail, feature_field, f"LLM API 调用失败: {e.response.status_code}")
    except Exception as e:
        logger.error(f"[_classify_kv_features] LLM error: {type(e).__name__}: {e}")
        return _build_failed_result(format_type, format_detail, feature_field, str(e), total_valid_lines=total_lines)

    # 6. 填充元数据字段
    format_name = normalize_log_format(format_type) or format_type
    result = {
        "status": parsed.get("status", "PARTIAL"),
        "log_format": format_name,
        "log_format_detail": format_detail or format_type,
        "feature_field": feature_field,
        "feature_identifier": _build_feature_identifier(format_type, format_detail),
        "feature_count": parsed.get("feature_count", len(parsed.get("classification_details", []))),
        "total_valid_lines": total_lines,
        "covered_lines": matched_lines,
        "coverage": _build_coverage_block(aggregation),
        "classification_details": parsed.get("classification_details", []),
        # CHANGED: 添加 analysis 字段（纯 KV 格式），语义：delimit=字段分隔符，tab=键值分隔符
        "analysis": {
            "has_json_structure": False,
            "has_cef_prefix": False,
            "has_key_value_pairs": True,
            "has_delimited_structure": False,
            "delimit": field_delimit or "判断失败",  # 字段分隔符
            "tab": kv_delimit or "判断失败",          # 键值分隔符
        },
        "categorical_features": feature_field,
        "Diversion_method": "日志类型",
        "fail_reason": "",
        "feature_body_group": 0,
        "feature_value_group": 0,
    }
    
    has_header = "日志头" in (format_detail or "").lower()
    if has_header:
        try:
            from agent.tools.pipeline.log_header_processor import _generate_kv_feature_identifier

            source_lines = [line for line in logs_str.splitlines() if line.strip()]
            classified_lines = [line for line in body_logs.splitlines() if line.strip()]
            matched_source_lines = [
                source
                for source, classified in zip(source_lines, classified_lines)
                if extractor.extract_value(classified, feature_field) is not None
            ]
            feature_identifier = _generate_kv_feature_identifier(
                "\n".join(matched_source_lines), kv_delimit
            )
            result["feature_identifier"] = feature_identifier
            result["feature_body_group"] = 1
            result["feature_value_group"] = 0
            logger.info(
                f"[_classify_kv_features] feature_identifier 生成成功: {feature_identifier}"
            )
        except ValueError:
            # 符合规范 7：错误处理原则（立即报错，不兜底）
            logger.error(
                "[_classify_kv_features] feature_identifier 生成失败; "
                f"source_lines={len(source_lines)}, "
                f"matched_lines={len(matched_source_lines)}"
            )
            # 快速失败：标记为 PARTIAL，而不是继续使用空字符串
            result["status"] = "PARTIAL"
            result["fail_reason"] = "feature_identifier 生成失败"
            result["feature_identifier"] = ""
            result["feature_body_group"] = 0
            result["feature_value_group"] = 0
    else:
        # 纯 KV 格式，不需要 feature_identifier
        result["feature_identifier"] = ""
        result["feature_body_group"] = 0
        result["feature_value_group"] = 0

    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 纯函数入口（chainlit_app 直接调用）
# ---------------------------------------------------------------------------

def _parse_format_info_dict(format_info: str) -> dict | None:
    """把 Step1 产出的 format_info JSON 串解析为字典，解析失败时返回 None 由调用方回退默认值。"""
    try:
        return json.loads(format_info) if format_info else None
    except Exception:
        logger.warning("[log_classifier] 解析 format_info 失败，使用默认值")
        return None


def _build_coverage_block(aggregation: dict) -> dict:
    """从聚合结果构建未匹配行覆盖信息；未匹配行不参与分类与规则生成，仅单独展示。"""
    total = aggregation.get("total_lines", 0)
    matched = aggregation.get("matched_lines", 0)
    return {
        "total_lines": total,
        "matched_lines": matched,
        "unmatched_lines": aggregation.get("unmatched_lines", total - matched),
        "unmatched_samples": aggregation.get("unmatched_samples", []),
    }


# 行首「标签: 」前缀（如 "Alarm: "），仅在去掉后能解锁特征键提取时才剥离
_LABEL_PREFIX_RE = _re_mod.compile(r"^(\S{1,32}):\s+")


def _kv_key_line_coverage(
    logs_str: str, feature_field: str, fmt: FormatContext, max_lines: int = 50
) -> float:
    """全行扫描特征键的行覆盖率（0~1），供确定性路由判定。"""
    from agent.tools.pipeline.extractors.kv_extractor import KvExtractor

    probe = KvExtractor(field_delimit=fmt.field_delimit, kv_delimit=fmt.kv_delimit)
    lines = [l for l in logs_str.strip().split("\n") if l.strip()][:max_lines]
    if not lines:
        return 0.0
    hit = sum(1 for line in lines if probe.extract_value(line, feature_field) is not None)
    return hit / len(lines)


# 派生候选排除的结构/噪声字符：kv 连接符、引号、JSON/时间戳/IP/URL 结构符号
_DERIVED_SEPARATOR_EXCLUDE = set('=: \t"\'`{}[]()<>.-/\\_+')


def _derive_separator_candidates(logs_str: str, max_lines: int = 50) -> list[str]:
    """从采样行统计高频结构符号，派生候选字段分隔符（#259 盲发现通道）。

    字段分隔符在多字段行中天然高频（N 个字段出现 N-1 次），只把平均每行
    出现 ≥2 次的符号交给覆盖率探针裁决；错误候选会被
    BODY_KEY_COVERAGE_THRESHOLD 阈值否决，因此宁可多派生、不靠枚举厂商。
    """
    from collections import Counter

    lines = [l for l in logs_str.strip().split("\n") if l.strip()][:max_lines]
    if not lines:
        return []
    freq = Counter(
        ch
        for line in lines
        for ch in line
        if not ch.isalnum() and ch not in _DERIVED_SEPARATOR_EXCLUDE
    )
    return [ch for ch, count in freq.most_common(8) if count >= 2 * len(lines)]


def _json_key_line_coverage(logs_str: str, feature_field: str, max_lines: int = 50) -> float:
    """JSON 特征键（含点分路径）的行覆盖率（0~1）。"""
    from agent.tools.pipeline.extractors.json_extractor import JsonExtractor

    probe = JsonExtractor()
    lines = [l for l in logs_str.strip().split("\n") if l.strip()][:max_lines]
    if not lines:
        return 0.0
    hit = sum(1 for line in lines if probe.extract_value(line, feature_field) is not None)
    return hit / len(lines)


def _normalize_body_key_lines(
    logs_str: str, feature_field: str, fmt: FormatContext
) -> str:
    """行级规范化：仅当该行提取不到特征键、且去掉行首『标签: 』前缀后能提取时才去前缀。

    混合形态日志（部分行 `Type=...` 直开头、部分行 `Alarm: Type=...` 带标签前缀）
    由此在同一次聚合里全部可提取；无前缀行与其他键不受影响。
    """
    from agent.tools.pipeline.extractors.kv_extractor import KvExtractor

    probe = KvExtractor(field_delimit=fmt.field_delimit, kv_delimit=fmt.kv_delimit)
    normalized = []
    for line in logs_str.split("\n"):
        if line.strip() and probe.extract_value(line, feature_field) is None:
            prefix = _LABEL_PREFIX_RE.match(line)
            if prefix:
                stripped = line[prefix.end() :]
                if probe.extract_value(stripped, feature_field) is not None:
                    normalized.append(stripped)
                    continue
        normalized.append(line)
    return "\n".join(normalized)


def _do_classify_log_features(
    logs_str: str,
    format_type: str = "unknown",
    format_detail: str = "",
    feature_field: str = "log_type",
    format_info: str = "",
    header_end_marker: str = "",
    feature_field_explicit: bool = False,
) -> str:
    """日志特征分类 —— 纯函数，无需 agno 上下文即可调用。

    路由逻辑（CHANGED 2026-06-02）：
    1. JSON 格式 → 纯 JSON 走 Path Main，日志头+JSON 走 Step 2a
    2. KV 格式 → 纯 KV 走 Path KV，日志头+KV 走 Step 2a
    3. 其他格式 → UNSUPPORTED

    注意:
        ``header_end_marker`` 会透传给下游函数，
        以便 ``match_real_samples`` 能从 ``real_samples`` 中剥离 syslog 头部。
    """
    ft = (format_type or "").lower()
    fd = (format_detail or "").lower()
    has_header = "日志头" in fd or "syslog" in fd
    is_json = ft == "json"
    is_kv = ft == "kv"

    # ---- 不支持的格式 ----
    if not is_json and not is_kv:
        logger.warning(f"[_do_classify_log_features] 不支持的格式: {format_type}")
        return json.dumps(
            {
                "status": "UNSUPPORTED",
                "error": f"不支持的日志格式: {format_type}",
                "log_format": normalize_log_format(format_type),
                "log_format_detail": format_detail or format_type,
                "feature_field": feature_field,
                "feature_identifier": "",
                "feature_count": 0,
                "total_valid_lines": 0,
                "covered_lines": 0,
                "classification_details": [],
            },
            ensure_ascii=False,
        )

    # ---- 用户显式指定的分类特征字段：跳过 Step 2a，强制按日志体路径使用该字段 ----
    # 不做任何头部剥离（Step 1 幻觉的 header_end_marker 可能等于字段分隔符，
    # 会把行首第一个字段——常为用户点名的特征字段——当日志头剥掉）。
    if feature_field_explicit and feature_field and feature_field.strip():
        logger.info(
            f"[_do_classify_log_features] 显式分类特征字段 '{feature_field}'，"
            f"跳过 Step 2a 直接按日志体提取"
        )
        explicit_info = _parse_format_info_dict(format_info)
        if is_kv:
            normalized = _normalize_body_key_lines(
                logs_str,
                feature_field,
                FormatContext.from_format_info(explicit_info),
            )
            return _classify_kv_features(
                logs_str=normalized,
                format_type=format_type,
                format_detail=format_detail,
                feature_field=feature_field,
                format_info=explicit_info,
                header_end_marker="",
            )
        return _classify_json_features(
            logs_str=logs_str,
            format_type=format_type,
            format_detail=format_detail,
            feature_field=feature_field,
            header_end_marker=header_end_marker,
        )

    # ---- 确定性路由：特征键作为日志体键覆盖绝大多数行时，跳过头部路由 ----
    # 特征键明明是日志体键时不走 Step 2a 头部聚类采样（避免采样覆盖丢失），
    # 有效 marker 由 KV 探针确认后剥头，无效 marker 回退整行；真头部特征保持原路由。
    if feature_field and feature_field.strip() and feature_field != "__header__":
        routing_info = _parse_format_info_dict(format_info) or {}
        if is_kv:
            routing_ctx = FormatContext.from_format_info(routing_info)
            normalized = _normalize_body_key_lines(
                logs_str, feature_field, routing_ctx
            )
            coverage = _kv_key_line_coverage(
                normalized, feature_field, routing_ctx
            )
            route = decide_body_key_route(feature_field, coverage)
            if route.use_body_path:
                logger.info(
                    f"[_do_classify_log_features] 特征键 '{feature_field}' 行覆盖率 "
                    f"{route.coverage:.0%}，跳过 Step 2a 按日志体确定性聚合"
                )
                return _classify_kv_features(
                    logs_str=normalized,
                    format_type=format_type,
                    format_detail=format_detail,
                    feature_field=feature_field,
                    format_info=routing_info,
                    header_end_marker=header_end_marker,
                )
        else:
            coverage = _json_key_line_coverage(logs_str, feature_field)
            route = decide_body_key_route(feature_field, coverage)
            if route.use_body_path:
                logger.info(
                    f"[_do_classify_log_features] JSON 特征键 '{feature_field}' 行覆盖率 "
                    f"{route.coverage:.0%}，跳过 Step 2a 按日志体确定性聚合"
                )
                return _classify_json_features(
                    logs_str=logs_str,
                    format_type=format_type,
                    format_detail=format_detail,
                    feature_field=feature_field,
                    header_end_marker="",
                )

    # ---- 日志头+KV：执行 Step 2a 特征定位 ----
    if is_kv and has_header:
        from agent.tools.pipeline.log_feature_locator import locate_feature

        # 分隔符经 FormatContext 单一解析后按名传递，杜绝历史上
        # log_classifier（delimit=字段分隔符）与 locate_feature（delimit=键值
        # 分隔符）两套同名反义约定在调用点交叉的活 bug（#344）。
        step2a_ctx = FormatContext.from_format_info(
            _parse_format_info_dict(format_info) or {}
        )

        logger.info("[_do_classify_log_features] 日志头+KV → Step 2a 特征定位")
        locate_result = locate_feature(
            logs_str=logs_str,
            feature_field=feature_field,
            format_type=format_type,
            format_detail=format_detail,
            fmt=step2a_ctx,
        )
        located = locate_result.get("feature_location", "body")
        located_field = locate_result.get("feature_field", "")
        reason = locate_result.get("reason", "")
        body_candidates = locate_result.get("body_candidates", 0)
        logger.info(
            f"[_do_classify_log_features] Step 2a 结果: "
            f"location={located}, field={located_field}, reason={reason[:80]}, body_candidates={body_candidates}"
        )

        # CHANGED: 添加验证逻辑（无兜底策略）
        if located == "body":
            # body 路径必须有 feature_field
            if not located_field:
                logger.error("[_do_classify_log_features] feature_location=body 但 feature_field 为空")
                return _build_failed_result(
                    format_type, format_detail, feature_field,
                    "Step 2a 判断错误：body 路径必须有 feature_field"
                )
        elif located == "header":
            # header 路径必须有正确的 feature_field
            if located_field != "__header__":
                logger.error(f"[_do_classify_log_features] feature_location=header 但 feature_field={located_field}")
                return _build_failed_result(
                    format_type, format_detail, feature_field,
                    f"Step 2a 判断错误：header 路径 feature_field 必须为 __header__（实际为 {located_field}）"
                )
            # CHANGED: 仅在 body 有大量候选（≥10）时记录警告，不强制失败（2026-06-05 修复数据1）
            if body_candidates >= 10:
                logger.warning(
                    f"[_do_classify_log_features] feature_location=header 但 body 有 {body_candidates} 个候选（可能误判），"
                    f"LLM 理由: {reason}，已信任 LLM 判断继续处理"
                )
        elif located == "unknown":
            logger.warning(f"[_do_classify_log_features] Step 2a 返回 unknown: {reason}")
            return _build_failed_result(
                format_type, format_detail, feature_field,
                f"特征定位失败: {reason}"
            )

        if located == "header":
            # Path A: 特征在日志头中
            logger.info("[_do_classify_log_features] → Path A (header)")
            from agent.tools.pipeline.log_header_processor import classify_header_features

            return classify_header_features(
                logs_str=logs_str,
                format_type=format_type,
                format_detail=format_detail,
                header_end_marker=header_end_marker,
                format_info=step2a_ctx.as_format_info(),  # 传递 Step1 确定的分隔符
            )

        if located == "body":
            # Path KV: 特征在 body 中，可能修正了 feature_field
            logger.info("[_do_classify_log_features] → Path KV (body, via Step 2a)")
            return _classify_kv_features(
                logs_str=logs_str,
                format_type=format_type,
                format_detail=format_detail,
                feature_field=located_field or feature_field,
                format_info=step2a_ctx.as_format_info(),  # 保留分隔符，修复 KV 分隔符丢失问题
                header_end_marker=header_end_marker,
            )

        # unknown → FAILED
        logger.warning(f"[_do_classify_log_features] Step 2a 返回 unknown: {reason}")
        return _build_failed_result(
            format_type, format_detail, feature_field,
            f"特征定位失败: {reason}",
        )

    # ---- 纯 KV：直接走 Path KV ----
    if is_kv:
        # 从 format_info 解析 delimit/tab
        info_dict = _parse_format_info_dict(format_info)

        logger.info("[_do_classify_log_features] → Path KV (纯KV)")
        return _classify_kv_features(
            logs_str=logs_str,
            format_type=format_type,
            format_detail=format_detail,
            feature_field=feature_field,
            format_info=info_dict,
            header_end_marker=header_end_marker,
        )

    # ---- 日志头+JSON：执行 Step 2a 特征定位 ----
    if has_header:
        from agent.tools.pipeline.log_feature_locator import locate_feature

        logger.info("[_do_classify_log_features] 日志头+JSON → Step 2a 特征定位")
        locate_result = locate_feature(
            logs_str=logs_str,
            feature_field=feature_field,
            format_type=format_type,
            format_detail=format_detail,
        )
        located = locate_result.get("feature_location", "body")
        located_field = locate_result.get("feature_field", feature_field)
        reason = locate_result.get("reason", "")
        logger.info(
            f"[_do_classify_log_features] Step 2a 结果: "
            f"location={located}, field={located_field}, reason={reason[:80]}"
        )

        if located == "header":
            # Path A: 特征在日志头中
            logger.info("[_do_classify_log_features] → Path A (header)")
            from agent.tools.pipeline.log_header_processor import classify_header_features

            return classify_header_features(
                logs_str=logs_str,
                format_type=format_type,
                format_detail=format_detail,
                header_end_marker=header_end_marker,
            )

        if located == "body":
            # Path Main: 特征在 body 中，可能修正了 feature_field
            logger.info("[_do_classify_log_features] → Path Main (body, via Step 2a)")
            return _classify_json_features(
                logs_str=logs_str,
                format_type=format_type,
                format_detail=format_detail,
                feature_field=located_field or feature_field,
                header_end_marker=header_end_marker,
            )

        # unknown → FAILED
        logger.warning(f"[_do_classify_log_features] Step 2a 返回 unknown: {reason}")
        return _build_failed_result(
            format_type, format_detail, feature_field,
            f"特征定位失败: {reason}",
        )

    # ---- 纯 JSON：直接走 Path Main ----
    logger.info("[_do_classify_log_features] → Path Main (纯JSON)")
    return _classify_json_features(
        logs_str=logs_str,
        format_type=format_type,
        format_detail=format_detail,
        feature_field=feature_field,
        header_end_marker=header_end_marker,
    )


# ---------------------------------------------------------------------------
# 工具入口（agno @tool 装饰器包装）
# ---------------------------------------------------------------------------


@tool(
    name="classify_log_features",
    description="识别日志的业务分类特征。输入 logs_str=原始日志字符串, format_type=格式类型, format_info=Step1输出的JSON字符串。",
)
def classify_log_features(
    logs_str: str,
    format_type: str = "unknown",
    format_detail: str = "",
    feature_field: str = "log_type",
    format_info: str = "",
) -> str:
    """日志特征分类工具 —— agno agent 集成的薄包装层。"""
    return _do_classify_log_features(
        logs_str=logs_str,
        format_type=format_type,
        format_detail=format_detail,
        feature_field=feature_field,
        format_info=format_info,
    )
