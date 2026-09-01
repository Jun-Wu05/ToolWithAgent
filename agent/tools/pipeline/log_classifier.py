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
from agent.tools.pipeline.classification_policy import decide_body_key_route

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


# ---------------------------------------------------------------------------
# 核心：统一的 JSON 分类（替代旧 Path B + C）
# ---------------------------------------------------------------------------

def _classify_json_features(
    logs_str: str,
    format_type: str,
    format_detail: str,
    feature_field: str,
    format_info: dict | None,
    header_end_marker: str = "",
) -> str:
    """统一的 JSON body 特征分类。

    使用 :class:`extractors.JsonExtractor` 提取值，
    :mod:`common.aggregator` 分组，LLM 语义分组，
    :mod:`common.llm_postprocessor` 清洗 + 知识库存储。
    """
    from agent.tools.pipeline.extractors.json_extractor import JsonExtractor
    from agent.tools.pipeline.common.llm_postprocessor import postprocess_llm_classification
    from agent.tools.pipeline.common.knowledge_store import store_classification_knowledge

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

    # 2. 准备 LLM 输入
    aggregated_values = aggregation.get("top_values", [])
    top_values_detail = {}
    for val in aggregated_values[:20]:
        info = aggregation["values"].get(val, {})
        top_values_detail[val] = {
            "count": info.get("count", 0),
            "samples": info.get("samples", []),
        }

    aggregated_json = json.dumps(top_values_detail, ensure_ascii=False)
    sampled_logs_str = sample_logs(logs_str, 5)
    format_name = normalize_log_format(format_type) or format_type

    # 3. 构建 prompt
    prompt = load_log_classify_prompt().format(
        format_type=format_name,
        format_detail=format_detail or format_type,
        feature_field=feature_field,
        aggregation_text=aggregated_json,
        sampled_logs=sampled_logs_str,
    )

    logger.info(
        f"[_classify_json_features] Calling LLM: "
        f"format={format_name}, field={feature_field}, "
        f"unique_values={len(aggregated_values)}, prompt_len={len(prompt)}"
    )

    # 4. 调用 LLM
    try:
        response = _call_llm_direct(prompt, temperature=0.2, max_tokens=8000, timeout=120)
    except httpx.HTTPStatusError as e:
        logger.error(f"[_classify_json_features] API error: {e}")
        return _build_failed_result(format_type, format_detail, feature_field, f"LLM API 调用失败: {e.response.status_code}")
    except Exception as e:
        logger.error(f"[_classify_json_features] LLM error: {type(e).__name__}: {e}")
        return _build_failed_result(format_type, format_detail, feature_field, str(e), total_valid_lines=total_lines)

    # 5. 后处理 LLM 响应
    parsed = postprocess_llm_classification(
        response, aggregation, logs_str,
        extractor_func=extractor.extract_value,
        feature_field=feature_field,
        header_end_marker=header_end_marker,
        sample_format="json",
    )

    # 6. 填充元数据字段
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

    # 7. 存入知识库
    if result["status"] == "SUCCESS":
        _sample_logs = [l for l in logs_str.strip().split("\n") if l.strip()][:10]
        store_classification_knowledge(
            classify_result=result,
            format_type=format_type,
            format_detail=format_detail,
            feature_field=feature_field,
            sample_logs=_sample_logs,
        )

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
    :mod:`common.llm_postprocessor` 清洗 + 知识库存储。
    """
    from agent.tools.pipeline.extractors.kv_extractor import KvExtractor
    from agent.tools.pipeline.common.llm_postprocessor import postprocess_llm_classification
    from agent.tools.pipeline.common.knowledge_store import store_classification_knowledge

    # 0. 校验输入
    if not logs_str or not logs_str.strip():
        return _build_failed_result(format_type, format_detail, feature_field, "日志内容为空")

    if not feature_field or not feature_field.strip():
        return _build_failed_result(format_type, format_detail, feature_field, "feature_field 为空，Step1 未识别出分类字段")

    # 1. 从 format_info 解析 delimit/tab（语义：delimit=字段分隔符，tab=键值分隔符）
    field_delimit = " "
    kv_delimit = "="
    if format_info:
        try:
            field_delimit = format_info.get("delimit", " ") or " "  # 字段分隔符
            kv_delimit = format_info.get("tab", "=") or "="          # 键值分隔符
        except Exception:
            logger.warning(f"[_classify_kv_features] 解析 format_info 失败，使用默认值")
            # CHANGED: 如果有日志头，使用 header_end_marker 提取日志体（2026-06-08 修复）
        # 符合规范 5：数据流向设计（上游数据格式 → 中间处理 → 下游使用）
        body_logs = logs_str
        if header_end_marker:
            # CHANGED (2026-08-07 修复 issue #14): 改用 strip_header_to_body 从左 split(marker, 1)，
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
                        f"[_classify_kv_features] 日志体为空，保留原始行: {line[:100]}"
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

            logger.info(
                f"[_classify_kv_features] 使用 header_end_marker='{header_end_marker}' 提取日志体: "
                f"成功={extracted_count}/{len(lines)}, "
                f"日志体示例（前50字符）: {body_logs[:50]}"
            )



    # 2. 使用 KvExtractor 提取 + 聚合（使用新参数名）
    extractor = KvExtractor(field_delimit=field_delimit, kv_delimit=kv_delimit)
    aggregation = extractor.extract_and_aggregate(body_logs, feature_field)

    total_lines = aggregation.get("total_lines", 0)
    matched_lines = aggregation.get("matched_lines", 0)

    # CHANGED: 如果使用默认分隔符匹配失败，尝试另一种分隔符（2026-06-05 修复数据3失败问题）
    if matched_lines == 0 and field_delimit == " " and kv_delimit == "=":
        logger.warning(
            f"[_classify_kv_features] 使用默认分隔符（空格+等号）匹配失败，尝试冒号分隔符"
        )
        extractor = KvExtractor(field_delimit=field_delimit, kv_delimit=":")
        aggregation = extractor.extract_and_aggregate(body_logs, feature_field)
        matched_lines = aggregation.get("matched_lines", 0)
        # 如果冒号分隔符成功，更新 kv_delimit
        if matched_lines > 0:
            kv_delimit = ":"
            logger.info(f"[_classify_kv_features] 冒号分隔符成功，匹配到 {matched_lines} 行")

    if matched_lines == 0 and field_delimit == " " and kv_delimit == ":":
        logger.warning(
            f"[_classify_kv_features] 冒号分隔符也失败，尝试等号分隔符"
        )
        extractor = KvExtractor(field_delimit=field_delimit, kv_delimit="=")
        aggregation = extractor.extract_and_aggregate(body_logs, feature_field)
        matched_lines = aggregation.get("matched_lines", 0)
        # 如果等号分隔符成功，更新 kv_delimit
        if matched_lines > 0:
            kv_delimit = "="
            logger.info(f"[_classify_kv_features] 等号分隔符成功，匹配到 {matched_lines} 行")

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

    # 2. 准备 LLM 输入
    aggregated_values = aggregation.get("top_values", [])
    top_values_detail = {}
    for val in aggregated_values[:20]:
        info = aggregation["values"].get(val, {})
        top_values_detail[val] = {
            "count": info.get("count", 0),
            "samples": info.get("samples", []),
        }

    aggregated_json = json.dumps(top_values_detail, ensure_ascii=False)
    sampled_logs_str = sample_logs(logs_str, 5)
    format_name = normalize_log_format(format_type) or format_type

    # 3. 构建 prompt
    prompt = load_log_classify_prompt().format(
        format_type=format_name,
        format_detail=format_detail or format_type,
        feature_field=feature_field,
        aggregation_text=aggregated_json,
        sampled_logs=sampled_logs_str,
    )

    logger.info(
        f"[_classify_kv_features] Calling LLM: "
        f"format={format_name}, field={feature_field}, "
        f"unique_values={len(aggregated_values)}, prompt_len={len(prompt)}"
    )

    # 4. 调用 LLM
    try:
        response = _call_llm_direct(prompt, temperature=0.2, max_tokens=8000, timeout=120)
    except httpx.HTTPStatusError as e:
        logger.error(f"[_classify_kv_features] API error: {e}")
        return _build_failed_result(format_type, format_detail, feature_field, f"LLM API 调用失败: {e.response.status_code}")
    except Exception as e:
        logger.error(f"[_classify_kv_features] LLM error: {type(e).__name__}: {e}")
        return _build_failed_result(format_type, format_detail, feature_field, str(e), total_valid_lines=total_lines)

    # 5. 后处理 LLM 响应
    parsed = postprocess_llm_classification(
        response, aggregation, logs_str,
        extractor_func=extractor.extract_value,
        feature_field=feature_field,
        header_end_marker=header_end_marker,
    )

    # 6. 填充元数据字段
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
            feature_identifier = _generate_kv_feature_identifier(logs_str)
            result["feature_identifier"] = feature_identifier
            result["feature_body_group"] = 1
            result["feature_value_group"] = 0
            logger.info(
                f"[_classify_kv_features] feature_identifier 生成成功: {feature_identifier}"
            )
        except ValueError as e:
            # 符合规范 7：错误处理原则（立即报错，不兜底）
            logger.error(
                f"[_classify_kv_features] feature_identifier 生成失败: {e}. "
                f"logs_str 前 100 字符: {logs_str[:100]}"
            )
            # 快速失败：标记为 PARTIAL，而不是继续使用空字符串
            result["status"] = "PARTIAL"
            result["fail_reason"] = f"feature_identifier 生成失败: {e}"
            result["feature_identifier"] = ""
            result["feature_body_group"] = 0
            result["feature_value_group"] = 0
    else:
        # 纯 KV 格式，不需要 feature_identifier
        result["feature_identifier"] = ""
        result["feature_body_group"] = 0
        result["feature_value_group"] = 0

    # 7. 存入知识库
    if result["status"] == "SUCCESS":
        _sample_logs = [l for l in logs_str.strip().split("\n") if l.strip()][:10]
        store_classification_knowledge(
            classify_result=result,
            format_type=format_type,
            format_detail=format_detail,
            feature_field=feature_field,
            sample_logs=_sample_logs,
        )

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
    logs_str: str, feature_field: str, delimit: str, tab: str, max_lines: int = 50
) -> float:
    """全行扫描特征键的行覆盖率（0~1），供确定性路由判定。"""
    from agent.tools.pipeline.extractors.kv_extractor import KvExtractor

    probe = KvExtractor(field_delimit=delimit, kv_delimit=tab)
    lines = [l for l in logs_str.strip().split("\n") if l.strip()][:max_lines]
    if not lines:
        return 0.0
    hit = sum(1 for line in lines if probe.extract_value(line, feature_field) is not None)
    return hit / len(lines)


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
    logs_str: str, feature_field: str, delimit: str, tab: str
) -> str:
    """行级规范化：仅当该行提取不到特征键、且去掉行首『标签: 』前缀后能提取时才去前缀。

    混合形态日志（部分行 `Type=...` 直开头、部分行 `Alarm: Type=...` 带标签前缀）
    由此在同一次聚合里全部可提取；无前缀行与其他键不受影响。
    """
    from agent.tools.pipeline.extractors.kv_extractor import KvExtractor

    probe = KvExtractor(field_delimit=delimit, kv_delimit=tab)
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
            info = explicit_info or {}
            normalized = _normalize_body_key_lines(
                logs_str,
                feature_field,
                info.get("delimit", ";") or ";",
                info.get("tab", "=") or "=",
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
            format_info=None,
            header_end_marker=header_end_marker,
        )

    # ---- 确定性路由：特征键作为日志体键覆盖绝大多数行时，跳过头部路由与剥离 ----
    # 特征键明明是日志体键时不走 Step 2a 头部聚类采样（避免采样覆盖丢失），
    # 也不应用任何 header_end_marker 剥离；真头部特征（键不在行内）保持原路由。
    if feature_field and feature_field.strip() and feature_field != "__header__":
        routing_info = _parse_format_info_dict(format_info) or {}
        if is_kv:
            routing_delimit = routing_info.get("delimit", ";") or ";"
            routing_tab = routing_info.get("tab", "=") or "="
            normalized = _normalize_body_key_lines(
                logs_str, feature_field, routing_delimit, routing_tab
            )
            coverage = _kv_key_line_coverage(
                normalized, feature_field, routing_delimit, routing_tab
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
                    header_end_marker="",
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
                    format_info=None,
                    header_end_marker="",
                )

    # ---- 日志头+KV：执行 Step 2a 特征定位 ----
    if is_kv and has_header:
        from agent.tools.pipeline.log_feature_locator import locate_feature

        # CHANGED: 修复 delimit/tab 默认值写反的问题（delimit=字段分隔符, tab=键值分隔符）
        info_dict = _parse_format_info_dict(format_info) or {}
        delimit = info_dict.get("delimit", ";") or ";"   # 字段分隔符默认值
        tab = info_dict.get("tab", "=") or "="           # 键值分隔符默认值

        logger.info("[_do_classify_log_features] 日志头+KV → Step 2a 特征定位")
        locate_result = locate_feature(
            logs_str=logs_str,
            feature_field=feature_field,
            format_type=format_type,
            format_detail=format_detail,
            delimit=delimit,
            tab=tab,
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
            # CHANGED: 传递 format_info（delimit/tab），确保 analysis 使用 Step1 确定性值
            logger.info("[_do_classify_log_features] → Path A (header)")
            from agent.tools.pipeline.log_header_processor import classify_header_features

            return classify_header_features(
                logs_str=logs_str,
                format_type=format_type,
                format_detail=format_detail,
                header_end_marker=header_end_marker,
                format_info={"delimit": delimit, "tab": tab},  # CHANGED: 传递 Step1 确定的分隔符
            )

        if located == "body":
            # Path KV: 特征在 body 中，可能修正了 feature_field
            # CHANGED: 传递 format_info 保留 delimit/tab（修复 KV 分隔符丢失问题）
            logger.info("[_do_classify_log_features] → Path KV (body, via Step 2a)")
            return _classify_kv_features(
                logs_str=logs_str,
                format_type=format_type,
                format_detail=format_detail,
                feature_field=located_field or feature_field,
                format_info={"delimit": delimit, "tab": tab},
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
                format_info=None,
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
        format_info=None,
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
