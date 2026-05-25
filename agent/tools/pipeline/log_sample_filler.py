# -*- coding: utf-8 -*-
"""
[Step 4] 替换样例日志 — 用 feature_identifier 从原始日志匹配真实样例。

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
    header_end_marker: str = "",
) -> dict:
    """
    用分类结果中的 feature_identifier 从原始日志匹配真实样例日志。

    对齐 Dify 工作流中"替换样例日志"代码节点的逻辑：
    对每个 classification_detail，用 feature_identifier 去原始日志中匹配真实行，
    替换模板占位符为真实日志行。

    Args:
        classification: classify_log_features 的输出 dict
        logs_str: 原始日志字符串
        max_samples_per_type: 每种分类最多取多少条真实样例
        feature_identifier: 双捕获组正则（group1=日志主体），用于提取日志主体而非整行
        header_end_marker: 日志头与 body 的分界标记（如 " - "），为空表示无头部。
                           优先从 classification["header_end_marker"] 获取。

    Returns:
        classification 的副本，每个 classification_detail 增加 "real_samples" 列表
    """
    details = classification.get("classification_details", [])
    if not details:
        return classification

    # Prefer header_end_marker from classification output (set by Step 3)
    if not header_end_marker:
        header_end_marker = classification.get("header_end_marker", "")

    # CHANGED: Auto-extract feature_identifier from classification dict,
    # so callers (e.g. chainlit_app.py) don't need to pass it explicitly.
    # This fixes Bug 2 where feature_identifier was not passed, causing
    # fi_pattern=None → real_samples = full line instead of body only.
    if not feature_identifier:
        feature_identifier = classification.get("feature_identifier", "")

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

    # Get body/value group indices from classification
    feature_body_group = classification.get("feature_body_group", 1)
    feature_value_group = classification.get("feature_value_group", 2)

    for detail in details:
        detail_copy = dict(detail)
        # Cleanup deprecated fields
        detail_copy.pop("matched_regex", None)
        detail_copy.pop("meaning", None)
        logtype = detail_copy.get("logtype", "")

        # 用 feature_identifier 双捕获组正则提取
        if fi_pattern and logtype:
            try:
                for line in lines:
                    m = fi_pattern.search(line)
                    if m and len(m.groups()) >= max(feature_body_group, feature_value_group):
                        if m.group(feature_value_group) == logtype:
                            # sample = 完整行（入口规则用）
                            detail_copy["sample"] = line

                            # real_samples: 优先用 body_group 提取日志主体
                            if m.lastindex and m.lastindex >= feature_body_group:
                                body_from_regex = m.group(feature_body_group)
                                if body_from_regex and body_from_regex != line:
                                    detail_copy["real_samples"] = body_from_regex
                                else:
                                    # body_group captured whole line — fallback to header_end_marker
                                    detail_copy["real_samples"] = _strip_header(
                                        line, header_end_marker
                                    )
                            else:
                                detail_copy["real_samples"] = _strip_header(
                                    line, header_end_marker
                                )
                            break
            except _re.error:
                pass

        # 匹配不到则尝试用 header_end_marker 直接剥离
        if not detail_copy.get("real_samples") and logtype:
            for line in lines:
                # Simple check: logtype appears in line
                if logtype in line:
                    detail_copy["sample"] = line
                    detail_copy["real_samples"] = _strip_header(line, header_end_marker)
                    break

        # 最终兜底: 仍然匹配不到
        if not detail_copy.get("real_samples"):
            detail_copy["real_samples"] = "[匹配失败]"

        result["classification_details"].append(detail_copy)

    return result


def _strip_header(line: str, header_end_marker: str) -> str:
    """用 header_end_marker 剥离日志头部，返回 body 部分。

    If marker is empty or not found in line, returns the full line.
    """
    if not header_end_marker:
        return line
    parts = line.split(header_end_marker, 1)
    if len(parts) == 2 and parts[1].strip():
        return parts[1].strip()
    return line