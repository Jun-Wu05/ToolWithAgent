"""
field_source 字段提取测试 — 日志解析结果路径 + 原始日志直接提取兜底。

回归背景（2026-07-29）：
  用户「提取日志类型 → alarm_name枚举提取+威胁映射」流程中，general 意图
  仍用 Excel 列头（发生时间/事件名称/...），而非日志字段（alarm_name/src_ip）。
  根因：field_source 只在 intent=mapping 时生效，且无日志解析时无兜底。
  修复：① general 意图也用日志字段 ② 无日志解析时从原始日志直接提取 KV 字段。
"""
from web.field_source import extract_log_fields_for_mapping, _extract_kv_fields_from_lines


# 真实 KV 日志行（启明天阗 syslog+kv 格式）
KV_LOG_LINES = [
    '<220>May 22 14:39:41 ips IPS: src_ip="120.55.65.26" dst_ip="172.18.18.125" '
    'alarm_name="SQL注入攻击" flow_id=200202 protocol_id=51 action="block"',
    '<414>May 22 09:06:28 ips AUDIT: log_type=2 src_ip="172.18.34.208" '
    'content="增加用户" threat_level=10 result="0"',
]


class TestExtractFromRawLogFallback:
    """无日志解析结果时，从原始日志行直接提取 KV 字段。"""

    def test_extract_kv_fields_from_raw_lines(self):
        """无 classification，有 raw_log_lines → 从日志行直接提取字段。"""
        fields = extract_log_fields_for_mapping(None, KV_LOG_LINES)
        assert "src_ip" in fields, f"应提取到 src_ip，实际：{fields}"
        assert "dst_ip" in fields, f"应提取到 dst_ip，实际：{fields}"
        assert "alarm_name" in fields, f"应提取到 alarm_name，实际：{fields}"
        assert "action" in fields, f"应提取到 action，实际：{fields}"

    def test_extract_excludes_excel_headers(self):
        """提取的字段是日志字段，不是 Excel 列头。"""
        fields = extract_log_fields_for_mapping(None, KV_LOG_LINES)
        assert "发生时间" not in fields, "不应含 Excel 列头「发生时间」"
        assert "事件名称" not in fields, "不应含 Excel 列头「事件名称」"

    def test_extract_deduplicates(self):
        """字段去重（src_ip 在两行都出现，只保留一个）。"""
        fields = extract_log_fields_for_mapping(None, KV_LOG_LINES)
        assert fields.count("src_ip") == 1

    def test_extract_empty_lines_returns_empty(self):
        """空日志行列表返回空。"""
        assert extract_log_fields_for_mapping(None, []) == []
        assert extract_log_fields_for_mapping(None, None) == []

    def test_extract_kv_fields_from_lines_directly(self):
        """直接测试 _extract_kv_fields_from_lines 纯函数。"""
        fields = _extract_kv_fields_from_lines(KV_LOG_LINES)
        assert "alarm_name" in fields
        assert "flow_id" in fields
        assert "protocol_id" in fields

    def test_extract_pipe_delimited(self):
        """竖线分隔的 KV 日志也能提取（奇安信NGSOC 格式）。"""
        lines = ["uuid=abc|name=远控木马|severity=危急|srcIp=[1.2.3.4]"]
        fields = _extract_kv_fields_from_lines(lines)
        assert "uuid" in fields
        assert "name" in fields
        assert "severity" in fields
        assert "srcIp" in fields
