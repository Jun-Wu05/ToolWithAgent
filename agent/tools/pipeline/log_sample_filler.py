# -*- coding: utf-8 -*-
"""
样例日志替换（Step 4）。

用 feature_identifier 双捕获组正则从原始日志中匹配真实样例，
替换 LLM 返回的占位符 sample，提取不含 syslog 头部的 JSON body。
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
    """用 feature_identifier 从原始日志匹配真实样例。

    对每个 classification_detail，用双捕获组正则匹配原始日志行，
    提取 JSON 主体（不含 syslog 头部）作为 real_samples。

    参数:
        classification: classify_log_features 的输出字典
        logs_str: 原始日志字符串
        max_samples_per_type: 每种分类最多取多少条样例
        feature_identifier: 双捕获组正则（Group1=JSON主体，Group2=特征值）
        header_end_marker: 日志头与 body 的分界标记
                           优先从 classification["header_end_marker"] 获取

    返回:
        classification 的副本，每个 detail 增加 "real_samples" 字段
    """
    details = classification.get("classification_details", [])
    if not details:
        return classification

    # 从 classification 中自动提取参数
    if not header_end_marker:
        header_end_marker = classification.get("header_end_marker", "")
    if not feature_identifier:
        feature_identifier = classification.get("feature_identifier", "")

    lines = [l for l in logs_str.strip().split("\n") if l.strip()]
    result = dict(classification)
    result["classification_details"] = []

    # 预编译正则
    fi_pattern = None
    if feature_identifier:
        try:
            fi_pattern = _re.compile(feature_identifier)
        except _re.error:
            logger.warning(f"[fill_sample_logs] feature_identifier 编译失败: {feature_identifier}")

    # 获取捕获组索引
    feature_body_group = classification.get("feature_body_group", 1)
    feature_value_group = classification.get("feature_value_group", 2)

    for detail in details:
        detail_copy = dict(detail)
        detail_copy.pop("matched_regex", None)
        detail_copy.pop("meaning", None)
        logtype = detail_copy.get("logtype", "")

        # 策略 A：用 feature_identifier 双捕获组正则提取
        if fi_pattern and logtype:
            try:
                for line in lines:
                    m = fi_pattern.search(line)
                    if m and len(m.groups()) >= max(feature_body_group, feature_value_group):
                        if m.group(feature_value_group) == logtype:
                            # sample = 完整行（入口规则用）
                            detail_copy["sample"] = line

                            # real_samples = body_group 提取 JSON 主体
                            body_from_regex = m.group(feature_body_group)
                            if body_from_regex and body_from_regex != line:
                                detail_copy["real_samples"] = body_from_regex
                            else:
                                # body_group 捕获了整行 — 回退到剥离头部
                                detail_copy["real_samples"] = _strip_header(
                                    line, header_end_marker
                                )
                            break
            except _re.error:
                pass

        # 策略 B：正则未匹配时，用子串匹配 + JSON body 提取
        if not detail_copy.get("real_samples") and logtype:
            for line in lines:
                if logtype in line:
                    detail_copy["sample"] = line
                    stripped = _strip_header(line, header_end_marker)
                    if stripped == line and "{" in line:
                        # 无 header_end_marker — 尝试提取 JSON body
                        json_body = _extract_json_body(line)
                        detail_copy["real_samples"] = json_body if json_body else line
                    else:
                        detail_copy["real_samples"] = stripped
                    break

        # 最终兜底
        if not detail_copy.get("real_samples"):
            detail_copy["real_samples"] = "[匹配失败]"

        result["classification_details"].append(detail_copy)

    return result


def _strip_header(line: str, header_end_marker: str) -> str:
    """用 header_end_marker 剥离日志头部，返回 body 部分。

    参数:
        line: 完整日志行
        header_end_marker: 头部结束标记（如 " - "）

    返回:
        剥离头部后的 body；标记为空或未找到时返回原始行
    """
    if not header_end_marker:
        return line
    parts = line.split(header_end_marker, 1)
    if len(parts) == 2 and parts[1].strip():
        return parts[1].strip()
    return line


def _extract_json_body(line: str) -> str | None:
    """从一行日志中提取 JSON 子串（从第一个 { 到最后一个 }）。

    适用于 syslog头+JSON 格式的日志行。

    参数:
        line: 完整日志行

    返回:
        JSON 子串（不含 syslog 头部），未找到时返回 None
    """
    json_start = line.find("{")
    json_end = line.rfind("}")
    if json_start != -1 and json_end > json_start:
        return line[json_start:json_end + 1]
    return None