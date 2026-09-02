# -*- coding: utf-8 -*-
"""日志特征值提取器的抽象基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ValueExtractor(ABC):
    """从日志行中提取特征值的策略接口。

    每个具体实现处理一种日志格式（JSON、KV、CSV 等），
    提供：
    - 单行值提取
    - 批量聚合（使用 ``common.aggregator.aggregate_by_field``）
    """

    @abstractmethod
    def extract_value(self, line: str, feature_field: str) -> Any:
        """从单条日志行中提取 ``feature_field`` 的值。

        Args:
            line:           单条日志行（原始字符串）。
            feature_field:  要提取的字段名（格式相关）。

        Returns:
            提取到的值，字段不存在或解析失败返回 None。
        """
        ...

    def extract_and_aggregate(
        self,
        logs_str: str,
        feature_field: str,
        max_lines: int = 2000,
    ) -> dict:
        """从所有行中提取特征值并按值聚合。

        默认实现委托给
        :func:`common.aggregator.aggregate_by_field`。

        Args:
            logs_str:      原始多行日志字符串。
            feature_field: 要聚合的字段名。
            max_lines:     最大处理行数。

        Returns:
            聚合结果字典。
        """
        from agent.tools.pipeline.common.aggregator import aggregate_by_field

        return aggregate_by_field(
            logs_str=logs_str,
            feature_field=feature_field,
            extractor=self.extract_value,
            max_lines=max_lines,
        )