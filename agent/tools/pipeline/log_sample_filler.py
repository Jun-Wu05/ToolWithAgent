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
        # CHANGED: 不再依赖 matched_regex，改用 feature_identifier 双捕获组正则
        detail_copy.pop("matched_regex", None)   # 防御性清理废弃字段
        detail_copy.pop("meaning", None)         # 防御性清理废弃字段
        logtype = detail_copy.get("logtype", "")

        # 用 feature_identifier 双捕获组正则提取（Group1=日志主体，Group2=特征值）
        if fi_pattern and logtype:
            try:
                for line in lines:
                    m = fi_pattern.search(line)
                    # CHANGED: lastindex 在嵌套捕获组中只反映最右侧 `)` 的组编号，
                    # 例如 (\{...(\w+)...\}) 的 lastindex=1，永远不满足 >=2，
                    # 改用 len(m.groups()) 判断捕获组数量
                    if m and len(m.groups()) >= 2 and m.group(2) == logtype:
                        detail_copy["real_samples"] = m.group(1)   # Group1 = 日志主体捕获组
                        detail_copy["sample"] = line               # sample = 完整原始日志行
                        break
            except _re.error:
                pass

        # 匹配不到则标记失败
        if not detail_copy.get("real_samples"):
            detail_copy["real_samples"] = "[匹配失败]"

        result["classification_details"].append(detail_copy)

    return result
