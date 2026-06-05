# -*- coding: utf-8 -*-
"""KV 格式特征提取器（支持多种分隔符）。"""

from __future__ import annotations

import re as _re
from typing import Any

from agent.tools.pipeline.extractors.base import ValueExtractor


# 默认正则：匹配 key=value 或 key="value"
# 支持值在引号内（可包含空格）或不在引号内（空格分隔）
_DEFAULT_KV_PATTERN = _re.compile(r'(?:^|\s)(\w+)=(?:"([^"\\]*(?:\\.[^"\\]*)*)"|([^\s"]+))')


class KvExtractor(ValueExtractor):
    """从 KV 格式日志行中提取特征值，支持多种分隔符。

    支持的格式：
    - delimit="=", tab=" " → key=value key2=value2
    - delimit=":", tab=" " → key:value key2:value2
    - delimit=":", tab="||" → key:value||key2:value2
    - 支持引号内的值（可包含分隔符）

    示例：
        src_ip=192.168.1.1 action=block level=high
        src_ip="192.168.1.1" action="block" level="high
        tag:waf_log_deface site_id:1351218462
        ver:2.0||mid:36658229b1914e6ffaf4c0ed84f1696c
    """

    def __init__(self, delimit: str = "=", tab: str = " "):
        """初始化 KV 提取器。

        Args:
            delimit: key-value 连接符（如 "=" 或 ":"）。
            tab: key-value 分隔符（如 " " 或 "||"）。
        """
        self.delimit = delimit
        self.tab = tab
        # 构建 tab 分隔符模式
        tab_pattern = r'\s+' if tab == "space" else _re.escape(tab)
        # 构建 delimit 分隔符模式（转义特殊字符）
        delimit_pattern = _re.escape(delimit)
        # CHANGED: 使用 \S+ 替代 \w+ 支持非 ASCII 字符（如中文 key）
        # 构建动态正则：(行首或tab分隔符) + key + delimit + "值" 或 非分隔符值
        self._pattern = _re.compile(
            rf'(?:^|{tab_pattern})(\S+)\s*{delimit_pattern}'
            rf'(?:"([^"\\]*(?:\\.[^"\\]*)*)"|([^{tab_pattern}"]+))'
        )

    def extract_value(self, line: str, feature_field: str) -> Any:
        """从 KV 日志行中提取字段值。

        Args:
            line: 单条日志行（原始字符串）。
            feature_field: 要查找的键名（如 "src_ip"、"action"）。

        Returns:
            提取到的值，字段不存在或解析失败返回 None。
        """
        if not line or not feature_field:
            return None

        # 遍历所有匹配的 KV 对
        for match in self._pattern.finditer(line):
            key = match.group(1)
            if key == feature_field:
                # 组2是引号内的值，组3是未引用的值
                quoted_value = match.group(2)
                unquoted_value = match.group(3)
                return quoted_value if quoted_value is not None else unquoted_value

        return None
