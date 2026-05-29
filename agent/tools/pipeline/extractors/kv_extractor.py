# -*- coding: utf-8 -*-
"""KV 格式特征提取器（骨架 —— 尚未实现）。"""

from __future__ import annotations

from typing import Any

from agent.tools.pipeline.extractors.base import ValueExtractor


class KvExtractor(ValueExtractor):
    """从 ``key=value`` 或 ``key:value`` 格式日志行中提取特征值。

    .. warning::
        尚未实现 —— 这是未来 KV 格式支持的占位符。
        所有方法均抛出 ``NotImplementedError``。
    """

    def extract_value(self, line: str, feature_field: str) -> Any:
        """从 KV 日志行中提取字段值。

        Args:
            line:           单条日志行。
            feature_field:  要查找的键名。

        Raises:
            NotImplementedError: 始终抛出，直到 KV 提取功能实现。
        """
        raise NotImplementedError(
            "KV format extraction is not yet implemented. "
            "This skeleton exists for future expansion."
        )

    def extract_and_aggregate(self, logs_str: str, feature_field: str, max_lines: int = 2000) -> dict:
        """聚合 KV 格式日志（尚未实现）。

        Raises:
            NotImplementedError: 始终抛出。
        """
        raise NotImplementedError(
            "KV format aggregation is not yet implemented."
        )