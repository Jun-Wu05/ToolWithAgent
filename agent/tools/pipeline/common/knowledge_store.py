# -*- coding: utf-8 -*-
"""
分类结果的统一知识库存储。

所有路径（A/B/C）共用此函数持久化分类知识，
避免重复实现。
"""

from __future__ import annotations

from agent.shared.logger import get_logger

logger = get_logger("log_parser_pipeline")


def store_classification_knowledge(
    classify_result: dict,
    format_type: str,
    format_detail: str = "",
    feature_field: str = "log_type",
    sample_logs: list[str] | None = None,
) -> bool:
    """将分类结果存储到知识库。

    封装 ``agent.tools.log_pattern_store`` 中的
    ``generate_structured_fingerprint`` 和 ``store_log_knowledge``。
    不抛出异常 —— 失败仅记录日志并静默处理，不影响主流程。

    Args:
        classify_result: 完整的分类结果字典（解析后的 LLM 输出）。
        format_type:     日志格式类型字符串（如 "json"）。
        format_detail:   详细的格式描述。
        feature_field:   分类字段名。
        sample_logs:     最多 10 条原始日志样本行，用于知识库存储。

    Returns:
        存储成功返回 True，否则返回 False。
    """
    try:
        from agent.tools.log_pattern_store import (
            generate_structured_fingerprint,
            store_log_knowledge,
        )

        structured_fp = generate_structured_fingerprint(
            classify_result=classify_result,
            format_detail=format_detail,
            feature_field=feature_field,
        )
        if not structured_fp:
            logger.info("[knowledge_store] Fingerprint is empty, skipping storage")
            return False

        application_id = store_log_knowledge(
            fingerprint=structured_fp,
            format_type=format_type,
            meta=classify_result,
            sample_logs=sample_logs or [],
        )
        if application_id is None:
            logger.warning("[knowledge_store] Storage created no application")
            return False
        logger.info(
            f"[knowledge_store] Stored application id={application_id}"
        )
        return True
    except Exception as store_err:
        logger.warning(f"[knowledge_store] Storage failed (non-fatal): {store_err}")
        return False
