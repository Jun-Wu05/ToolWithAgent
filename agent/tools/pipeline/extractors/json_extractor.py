# -*- coding: utf-8 -*-
"""JSON 格式特征提取器。"""

from __future__ import annotations

from typing import Any

from agent.tools.pipeline.extractors.base import ValueExtractor


class JsonExtractor(ValueExtractor):
    """从 JSON 日志行中提取特征值。

    通过 :func:`common.json_utils.try_extract_json_feature`
    支持纯 JSON 和 syslog 头部 + JSON 两种格式。
    """

    def extract_value(self, line: str, feature_field: str) -> Any:
        """从 JSON 日志行中提取字段值。

        Args:
            line:           单条日志行。
            feature_field:  点分隔的字段路径（如 ``"event.action"``）。

        Returns:
            字段值，未找到返回 None。
        """
        from agent.tools.pipeline.common.json_utils import try_extract_json_feature

        return try_extract_json_feature(line, feature_field)

    def extract_and_aggregate(
        self,
        logs_str: str,
        feature_field: str,
        max_lines: int = 2000,
        header_end_marker: str = "",
    ) -> dict:
        """从所有行中提取特征值并按值聚合。

        Args:
            logs_str:         原始多行日志字符串。
            feature_field:    要聚合的字段名。
            max_lines:        最大处理行数。
            header_end_marker: 日志头与 body 的分隔符（用于剥离日志头）。

        Returns:
            聚合结果字典。
        """
        from agent.tools.pipeline.common.aggregator import aggregate_by_field

        return aggregate_by_field(
            logs_str=logs_str,
            feature_field=feature_field,
            extractor=self.extract_value,
            max_lines=max_lines,
            header_end_marker=header_end_marker,
            is_json=True,
        )