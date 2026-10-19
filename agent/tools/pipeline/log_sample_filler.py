# -*- coding: utf-8 -*-
"""
样例日志替换（Step 4）。

保留上游确定性分类已绑定的真实样例；仅对缺失样本使用
feature_identifier 双捕获组严格补齐，并提取不含 syslog 头部的 body。
"""

from __future__ import annotations

import re as _re

from agent.shared.logger import get_logger
from agent.tools.pipeline.common.json_utils import extract_json_body

logger = get_logger("log_parser_pipeline")


def fill_sample_logs(
    classification: dict,
    logs_str: str,
    max_samples_per_type: int = 3,
    feature_identifier: str = "",
    header_end_marker: str = "",
) -> dict:
    """保留已绑定样本，并用 feature_identifier 严格补齐缺失样本。

    对每个 classification_detail，已有 sample / real_samples 均不改写；
    仅当 sample 缺失时，用双捕获组正则匹配原始日志行，且
    捕获值必须与 logtype 严格相等。

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

        # 上游分类器已用确定性 extractor 建立类型血缘；本步只补齐 body，
        # 不得为了补 real_samples 而重新搜索并改写权威 sample。
        existing_sample = detail_copy.get("sample")
        if existing_sample:
            if not detail_copy.get("real_samples"):
                body_from_sample = None
                if fi_pattern and feature_body_group > 0:
                    match = fi_pattern.search(existing_sample)
                    if match and len(match.groups()) >= feature_body_group:
                        body_from_sample = match.group(feature_body_group)
                if not body_from_sample:
                    body_from_sample = _strip_header(existing_sample, header_end_marker)
                if body_from_sample == existing_sample and "{" in existing_sample:
                    body_from_sample = extract_json_body(existing_sample) or existing_sample
                detail_copy["real_samples"] = body_from_sample or existing_sample
            result["classification_details"].append(detail_copy)
            continue

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

        # 最终兜底：无法严格匹配就显式失败，不借用“包含类型名”的其他日志。
        if not detail_copy.get("real_samples"):
            detail_copy["sample"] = "[匹配失败]"
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

    Note:
        本函数仅在 JSON 格式（Step 3 样本回填）下使用，因此优先用
        :func:`extract_json_body` 从第一个 ``{`` 提取到最后一个 ``}``，
        避免 syslog 头部含多个空格时 ``split(marker, 1)`` 从首个空格误切断。
    """
    from agent.tools.pipeline.common.json_utils import strip_header_to_body

    body = strip_header_to_body(line, header_end_marker, is_json=True)
    return body.strip() if body and body != line else body
