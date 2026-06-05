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
    - field_delimit=" ", kv_delimit="=" → key=value key2=value2
    - field_delimit=" ", kv_delimit=":" → key:value key2:value2
    - field_delimit="||", kv_delimit=":" → key:value||key2:value2
    - 支持引号内的值（可包含分隔符）

    示例：
        src_ip=192.168.1.1 action=block level=high
        src_ip="192.168.1.1" action="block" level="high
        tag:waf_log_deface site_id:1351218462
        ver:2.0||mid:36658229b1914e6ffaf4c0ed84f1696c

    参数说明：
        field_delimit: 字段分隔符（如 " " 或 "||"）
        kv_delimit: 键值分隔符（如 "=" 或 ":"）
    """

    def __init__(
        self,
        delimit: str = None,      # CHANGED: 旧参数名（向后兼容），实际语义是 kv_delimit
        tab: str = None,          # CHANGED: 旧参数名（向后兼容），实际语义是 field_delimit
        field_delimit: str = " ",  # CHANGED: 新参数名，字段分隔符
        kv_delimit: str = "=",     # CHANGED: 新参数名，键值分隔符
    ):
        """初始化 KV 提取器。

        Args:
            delimit: （已废弃）键值分隔符，请使用 kv_delimit
            tab: （已废弃）字段分隔符，请使用 field_delimit
            field_delimit: 字段分隔符（如 " " 或 "||"）
            kv_delimit: 键值分隔符（如 "=" 或 ":"）
        """
        # CHANGED: 向后兼容：如果使用旧参数名，映射到新参数名
        if delimit is not None:
            kv_delimit = delimit
        if tab is not None:
            field_delimit = tab

        self.field_delimit = field_delimit
        self.kv_delimit = kv_delimit

        # CHANGED: 修改参数名，但保留 self.delimit 和 self.tab 以兼容旧代码
        self.delimit = kv_delimit    # 键值分隔符（向后兼容）
        self.tab = field_delimit     # 字段分隔符（向后兼容）

        # CHANGED: 构建 field_delimit 分隔符模式（字段分隔符）
        field_pattern = r'\s+' if field_delimit == "space" else _re.escape(field_delimit)
        # CHANGED: 构建 kv_delimit 分隔符模式（键值分隔符）
        kv_pattern = _re.escape(kv_delimit)

        # CHANGED: 使用 \S+ 替代 \w+ 支持非 ASCII 字符（如中文 key）
        # 构建动态正则：(行首或field_delimit分隔符) + key + kv_delimit + "值" 或 非分隔符值
        self._pattern = _re.compile(
            rf'(?:^|{field_pattern})(\S+)\s*{kv_pattern}'
            rf'(?:"([^"\\]*(?:\\.[^"\\]*)*)"|([^{field_pattern}"]+))'
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
