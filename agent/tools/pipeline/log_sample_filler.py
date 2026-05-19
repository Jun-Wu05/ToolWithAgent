# -*- coding: utf-8 -*-
"""
[Step 4] 替换样例日志 — 用 matched_regex 从原始日志匹配真实样例。

对齐 Dify 工作流中"替换样例日志"代码节点。
"""

from __future__ import annotations

import re as _re

from agent.shared.logger import get_logger

logger = get_logger("log_parser_pipeline")


def fill_sample_logs(
    classification: dict,
    logs_str: str,
    max_samples_per_type: int = 3,
    feature_identifier: str = "",
) -> dict:
    """
    用分类结果中的 matched_regex 从原始日志匹配真实样例日志。

    对齐 Dify 工作流中"替换样例日志"代码节点的逻辑：
    对每个 classification_detail，用其 matched_regex 去原始日志中匹配真实行，
    替换模板占位符为真实日志行。

    Args:
        classification: classify_log_features 的输出 dict
        logs_str: 原始日志字符串
        max_samples_per_type: 每种分类最多取多少条真实样例
        feature_identifier: 双捕获组正则（group1=日志主体），用于提取日志主体而非整行

    Returns:
        classification 的副本，每个 classification_detail 增加 "real_samples" 列表
    """
    details = classification.get("classification_details", [])
    if not details:
        return classification

    lines = [l for l in logs_str.strip().split("\n") if l.strip()]
    result = dict(classification)
    result["classification_details"] = []

    # 预编译 feature_identifier 正则（group1 提取日志主体）
    fi_pattern = None
    if feature_identifier:
        try:
            fi_pattern = _re.compile(feature_identifier)
        except _re.error:
            logger.warning(f"[fill_sample_logs] feature_identifier 编译失败: {feature_identifier}")

    for detail in details:
        detail_copy = dict(detail)
        matched_regex = detail_copy.get("matched_regex", "")
        # 策略 A：feature_identifier 可用时，用 matched_regex 搜索行
        # real_samples 存 matched_regex 的 Group 1（日志主体值），sample 存完整行
        if fi_pattern and matched_regex:
            try:
                m_regex = _re.compile(matched_regex)
                for line in lines:
                    m_body = m_regex.search(line)
                    if m_body:
                        body_text = (
                            m_body.group(1)
                            if m_body.lastindex and m_body.lastindex >= 1
                            else line
                        )
                        detail_copy["real_samples"] = body_text
                        detail_copy["sample"] = line
                        break
            except _re.error:
                pass

        # 策略 B：无 feature_identifier 时，用 matched_regex 提取 Group 1
        if not detail_copy.get("real_samples") and matched_regex:
            try:
                pattern = _re.compile(matched_regex)
                for line in lines:
                    m_body = pattern.search(line)
                    if m_body:
                        body_text = (
                            m_body.group(1)
                            if m_body.lastindex and m_body.lastindex >= 1
                            else line
                        )
                        detail_copy["real_samples"] = body_text
                        if not detail_copy.get("sample"):
                            detail_copy["sample"] = line
                        break
            except _re.error as e:
                logger.warning(
                    f"[fill_sample_logs] 正则编译失败: {matched_regex}, 错误: {e}"
                )
                detail_copy["regex_error"] = str(e)

        # 兜底：用原始 sample 字段
        if not detail_copy.get("real_samples") and detail_copy.get("sample"):
            detail_copy["real_samples"] = detail_copy["sample"]

        result["classification_details"].append(detail_copy)

    return result