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