# -*- coding: utf-8 -*-
"""KV 格式特征提取器（支持多种分隔符）。"""

from __future__ import annotations

import re as _re
from typing import Any

from agent.tools.pipeline.extractors.base import ValueExtractor


# 默认正则：匹配 key=value 或 key="value"
# 支持值在引号内（可包含空格）或不在引号内（空格分隔）
_DEFAULT_KV_PATTERN = _re.compile(r'(?:^|\s)(\w+)=(?:"([^"\\]*(?:\\.[^"\\]*)*)"|([^\s"]+))')


# CHANGED: 定义需要清理的异常字符常量（2026-06-16 新增）
# BOM 字符
BOM_CHARS = ['\ufeff', '\ufeff', '\ufeff']
# 零宽字符
ZERO_WIDTH_CHARS = ['\u200b', '\u200c', '\u200d', '\u200e', '\u200f']
# 控制字符（保留换行、回车、制表符）
CONTROL_CHARS = [chr(i) for i in range(0x00, 0x20) if i not in [0x09, 0x0a, 0x0d]]
# 其他特殊字符
SPECIAL_CHARS = ['\ufffe', '\uffff', '\u2028', '\u2029', '\u00a0', '\u3000']
# 所有异常字符
ALL_SPECIAL_CHARS = BOM_CHARS + ZERO_WIDTH_CHARS + CONTROL_CHARS + SPECIAL_CHARS


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
        field_delimit: str = None,  # CHANGED: 新参数名，字段分隔符，删除硬编码默认值（2026-06-08 修复）
        kv_delimit: str = None,     # CHANGED: 新参数名，键值分隔符，删除硬编码默认值（2026-06-08 修复）
        clean_special_chars: bool = True,  # CHANGED: 是否清理异常字符（2026-06-16 新增）
    ):
        """初始化 KV 提取器。

        Args:
            delimit: （已废弃）键值分隔符，请使用 kv_delimit
            tab: （已废弃）字段分隔符，请使用 field_delimit
            field_delimit: 字段分隔符（如 " " 或 "||"），必须由上游提供
            kv_delimit: 键值分隔符（如 "=" 或 ":"），必须由上游提供
            clean_special_chars: 是否清理异常字符（默认 True）
        
        Raises:
            ValueError: 如果 field_delimit 或 kv_delimit 为 None
        """
        # CHANGED: 向后兼容：如果使用旧参数名，映射到新参数名
        if delimit is not None:
            kv_delimit = delimit
        if tab is not None:
            field_delimit = tab

        # CHANGED: 添加参数校验，强制上游提供完整信息（2026-06-08 修复）
        if field_delimit is None:
            raise ValueError(
                "field_delimit 不能为 None。"
                "请从 format_info 中获取，或使用已废弃的 tab 参数。"
            )
        if kv_delimit is None:
            raise ValueError(
                "kv_delimit 不能为 None。"
                "请从 format_info 中获取，或使用已废弃的 delimit 参数。"
            )

        self.field_delimit = field_delimit
        self.kv_delimit = kv_delimit
        self.clean_special_chars = clean_special_chars

        # CHANGED: 修改参数名，但保留 self.delimit 和 self.tab 以兼容旧代码
        self.delimit = kv_delimit    # 键值分隔符（向后兼容）
        self.tab = field_delimit     # 字段分隔符（向后兼容）

        # CHANGED: 构建 field_delimit 分隔符模式（字段分隔符）
        field_pattern = r'\s+' if field_delimit == "space" else _re.escape(field_delimit)
        # CHANGED: 构建 kv_delimit 分隔符模式（键值分隔符）
        kv_pattern = _re.escape(kv_delimit)

        # CHANGED: 使用 \S+ 替代 \w+ 支持非 ASCII 字符（如中文 key）
        # CHANGED: 在字段分隔符后面添加 \s*（可选空格），兼容分隔符后面有空格或没有空格的情况（2026-06-08 修复）
        # 构建动态正则：(行首或field_delimit分隔符+可选空格) + key + kv_delimit + "值" 或 非分隔符值
        self._pattern = _re.compile(
            rf'(?:^|{field_pattern}\s*)(\S+)\s*{kv_pattern}'
            rf'(?:"([^"\\]*(?:\\.[^"\\]*)*)"|([^{field_pattern}"]+))'
        )

    def _clean_special_chars(self, text: str, context: str = "") -> tuple[str, dict]:
        """清理文本中的异常字符。
        
        Args:
            text: 待清理的文本
            context: 上下文信息（用于日志）
        
        Returns:
            (清理后的文本, 清理统计信息)
        """
        if not text or not self.clean_special_chars:
            return text, {}
        
        cleaned = text
        stats = {
            'bom': 0,
            'zero_width': 0,
            'control': 0,
            'special': 0,
            'total': 0,
            'chars': []
        }
        
        # 1. 清理 BOM
        for char in BOM_CHARS:
            count = cleaned.count(char)
            if count > 0:
                stats['bom'] += count
                stats['total'] += count
                stats['chars'].append({'char': repr(char), 'count': count, 'type': 'bom'})
                cleaned = cleaned.replace(char, '')
        
        # 2. 清理零宽字符
        for char in ZERO_WIDTH_CHARS:
            count = cleaned.count(char)
            if count > 0:
                stats['zero_width'] += count
                stats['total'] += count
                stats['chars'].append({'char': repr(char), 'count': count, 'type': 'zero_width'})
                cleaned = cleaned.replace(char, '')
        
        # 3. 清理控制字符（保留换行、回车、制表符）
        for char in CONTROL_CHARS:
            count = cleaned.count(char)
            if count > 0:
                stats['control'] += count
                stats['total'] += count
                stats['chars'].append({'char': repr(char), 'count': count, 'type': 'control'})
                cleaned = cleaned.replace(char, '')
        
        # 4. 清理其他特殊字符
        for char in SPECIAL_CHARS:
            count = cleaned.count(char)
            if count > 0:
                stats['special'] += count
                stats['total'] += count
                stats['chars'].append({'char': repr(char), 'count': count, 'type': 'special'})
                cleaned = cleaned.replace(char, '')
        
        # 记录日志
        if stats['total'] > 0:
            from agent.shared.logger import get_logger
            logger = get_logger("log_parser_pipeline")
            
            # 构建清理详情
            details = []
            for item in stats['chars']:
                details.append(f"{item['char']}: {item['count']}个({item['type']})")
            
            # 截取前100字符用于日志
            preview = text[:100].replace('\n', '\\n').replace('\r', '\\r')
            cleaned_preview = cleaned[:100].replace('\n', '\\n').replace('\r', '\\r')
            
            logger.debug(
                f"[KvExtractor] 清理异常字符: 共 {stats['total']} 个, "
                f"context={context}, "
                f"详情: {'; '.join(details)}, "
                f"原始前100字符: {preview}, "
                f"清理后前100字符: {cleaned_preview}"
            )
        
        return cleaned, stats

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

        # CHANGED: 清理整行中的异常字符（2026-06-16 修复）
        cleaned_line, line_stats = self._clean_special_chars(line, f"line:feature={feature_field}")

        # 可以关闭清理（性能考虑）
        # extractor = KvExtractor(field_delimit=' ', kv_delimit='=', clean_special_chars=False)
        
        # 遍历所有匹配的 KV 对
        for match in self._pattern.finditer(cleaned_line):
            key = match.group(1)
            if key == feature_field:
                # 组2是引号内的值，组3是未引用的值
                quoted_value = match.group(2)
                unquoted_value = match.group(3)
                value = quoted_value if quoted_value is not None else unquoted_value
                
                # CHANGED: 清理值中的异常字符（双重保障）（2026-06-16 修复）
                if value and isinstance(value, str):
                    cleaned_value, value_stats = self._clean_special_chars(
                        value, f"value:key={feature_field}"
                    )
                    value = cleaned_value
                    
                    # 处理首尾的引号
                    if len(value) >= 2:
                        if (value[0] == '"' and value[-1] == '"') or \
                           (value[0] == "'" and value[-1] == "'"):
                            value = value[1:-1]
                    
                    # 去除换行符等控制字符（如果之前没清理干净）
                    value = value.replace('\n', '').replace('\r', '').replace('\t', '')
                
                return value

        return None

    def extract_and_aggregate(
        self,
        logs_str: str,
        feature_field: str,
        max_lines: int = 2000,
        header_end_marker: str = "",
    ) -> dict:
        """从所有行中提取特征值并按值聚合。

        重写基类方法，传递分隔符参数给聚合器。

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
            kv_delimit=self.kv_delimit,
            field_delimit=self.field_delimit,
            header_end_marker=header_end_marker,
        )