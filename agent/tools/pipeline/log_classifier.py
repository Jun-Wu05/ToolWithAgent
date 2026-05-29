# -*- coding: utf-8 -*-
"""
Step 3 — 日志特征分类器。

将日志分类路由到相应的提取器策略，
调用 LLM 进行语义分组，并对结果进行后处理。

路径：
- Path A: has_header_feature=true  → 头部提取器 (log_header_processor)
- Path Main: feature_location=body  → JSON 提取器 + LLM
- Unsupported: feature_location=header 但 has_header_feature=false
"""

from __future__ import annotations

import json

import httpx
from agno.tools import tool

from agent.core.prompts import load_log_classify_feature_prompt as load_log_classify_prompt
from agent.shared.logger import get_logger
from agent.tools.enum_extract_tool import sample_logs
from agent.tools.pipeline.llm_client import (
    _call_llm_direct,
    normalize_log_format,
)

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
        "classification_details": parsed.get("classification_details", []),
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
# 纯函数入口（chainlit_app 直接调用）
# ---------------------------------------------------------------------------

def _do_classify_log_features(
    logs_str: str,
    format_type: str = "unknown",
    format_detail: str = "",
    feature_field: str = "log_type",
    format_info: str = "",
    header_end_marker: str = "",
) -> str:
    """日志特征分类 —— 纯函数，无需 agno 上下文即可调用。

    路由：
    - Path A: has_header_feature=true  → log_header_processor
    - Path Main: feature_location=body  → _classify_json_features
    - Unsupported: header 但无 has_header_feature → UNSUPPORTED

    注意:
        ``header_end_marker`` 会透传给 :func:`_classify_json_features`，
        以便 ``match_real_samples`` 能从 ``real_samples`` 中剥离 syslog 头部。
    """
    # 解析 Step 1 的 format_info
    info_dict: dict | None = None
    has_header_feature = False
    feature_location = "unknown"

    if format_info:
        try:
            info_dict = json.loads(format_info) if isinstance(format_info, str) else format_info
            has_header_feature = bool(info_dict.get("has_header_feature", False))
            feature_location = str(info_dict.get("feature_location", "unknown")).lower()
        except (json.JSONDecodeError, TypeError):
            logger.warning("[_do_classify_log_features] format_info 解析失败，忽略")

    ft = (format_type or "").lower()

    # Path A: 头部特征分类
    if has_header_feature and ft == "json":
        logger.info("[_do_classify_log_features] → Path A (header)")
        from agent.tools.pipeline.log_header_processor import classify_header_features

        return classify_header_features(
            logs_str=logs_str,
            format_type=format_type,
            format_detail=format_detail,
        )

    # Path Main: body 特征分类
    if feature_location == "body" and ft == "json":
        logger.info("[_do_classify_log_features] → Path Main (body)")
        return _classify_json_features(
            logs_str=logs_str,
            format_type=format_type,
            format_detail=format_detail,
            feature_field=feature_field,
            format_info=info_dict,
            header_end_marker=header_end_marker,
        )

    # Unsupported: feature_location=header 但无 has_header_feature
    if feature_location == "header":
        logger.warning("[_do_classify_log_features] feature_location=header but has_header_feature=false → UNSUPPORTED")
        return json.dumps(
            {
                "status": "UNSUPPORTED",
                "error": "feature_location=header 且 has_header_feature=false，暂不支持",
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

    # Fallback: JSON 格式但无具体 location 信息
    if ft == "json":
        logger.info("[_do_classify_log_features] → Fallback JSON classification")
        return _classify_json_features(
            logs_str=logs_str,
            format_type=format_type,
            format_detail=format_detail,
            feature_field=feature_field,
            format_info=info_dict,
            header_end_marker=header_end_marker,
        )

    # 未知格式
    logger.warning(f"[_do_classify_log_features] Unsupported format: {format_type}")
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