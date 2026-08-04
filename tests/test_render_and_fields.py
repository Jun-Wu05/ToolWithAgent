"""
render_log_parser_result + 日志字段提取 测试。

问题 A 回归：real_samples 含 | 时，Markdown 表格渲染会截断。
  KV 日志行 uuid=xxx|name=yyy|... 在表格 `| 特征值 | 样例 |` 中，
  样例的 | 被当列分隔符，只显示第一个 | 之前的内容。
  修复：样例改用代码块展示，| 不再被解析。

问题 B 回归：自然语言「映射」用了 Excel 列头（decoded_fields），
  而非日志真实字段。应复用按钮路径：从 log_classification 生成子规则，
  提取 normalize 里的字段。
"""
import pytest

# conftest 已注入根路径
from web.utils import render_log_parser_result


# 真实 KV 日志行（含 | 分隔符）
KV_SAMPLE = "uuid=3cc90c2c|name=远控木马活动事件|severity=危急|srcIp=[10.16.2.12]"


class TestRenderRealSamplesNotTruncated:
    """问题 A：real_samples 不应被 Markdown 表格 | 截断。"""

    def test_kv_sample_shown_in_full(self):
        """KV 样例完整显示，uuid/name/severity 都在。"""
        classification = {
            "status": "SUCCESS",
            "log_format": "KV",
            "log_format_detail": "纯KV",
            "feature_field": "name",
            "feature_count": 1,
            "classification_details": [
                {"logtype": "远控木马活动事件", "real_samples": KV_SAMPLE}
            ],
        }
        result = render_log_parser_result(classification, None)
        # 修复前：表格里 real_samples 的 | 被截断，只剩 uuid=3cc90c2c
        # 修复后：完整 KV 行应全部出现
        assert "name=远控木马活动事件" in result, (
            "real_samples 被表格 | 截断，name 字段丢失"
        )
        assert "severity=危急" in result, "severity 字段也丢失"
        assert "srcIp=[10.16.2.12]" in result, "srcIp 字段也丢失"

    def test_kv_sample_not_split_into_columns(self):
        """regression：确认样例没有被切成多个表格列。"""
        classification = {
            "status": "SUCCESS",
            "log_format": "KV",
            "feature_field": "name",
            "feature_count": 1,
            "classification_details": [
                {"logtype": "test", "real_samples": KV_SAMPLE}
            ],
        }
        result = render_log_parser_result(classification, None)
        # 样例应以代码块形式出现（``` 包裹），而非裸表格行
        assert "```" in result, "KV 样例应用代码块包裹，避免 | 被当表格列分隔符"


class TestExtractLogFieldsForMapping:
    """问题 B：自然语言映射应从日志提取字段，而非用 Excel 列头。"""

    def test_extract_fields_from_classification(self):
        """从 log_classification 提取真实日志字段（uuid/srcIp/severity），而非 Excel 列头。"""
        from web.field_source import extract_log_fields_for_mapping

        # 模拟日志解析结果（含 analysis 分隔符信息，与真实 pipeline 输出一致）
        classification = {
            "status": "SUCCESS",
            "log_format": "KV",
            "feature_field": "name",
            "analysis": {"delimit": "|", "tab": "="},  # KV 分隔符
            "classification_details": [
                {"logtype": "远控木马活动事件", "sample": KV_SAMPLE}
            ],
        }
        raw_log_lines = [KV_SAMPLE]
        fields = extract_log_fields_for_mapping(classification, raw_log_lines)
        # 应提取到日志 KV 字段（uuid/srcIp/severity），不是 Excel 列头（发生时间/事件名称）
        assert "uuid" in fields, f"应含日志字段 uuid，实际：{fields}"
        assert "srcIp" in fields, f"应含日志字段 srcIp，实际：{fields}"
        assert "severity" in fields, f"应含日志字段 severity，实际：{fields}"
        # 关键回归：不应是 Excel 列头
        assert "发生时间" not in fields, "不应含 Excel 列头「发生时间」"
        assert "事件名称" not in fields, "不应含 Excel 列头「事件名称」"

    def test_extract_returns_empty_without_classification(self):
        """无日志解析结果时返回空列表（调用方据此决定是否提示）。"""
        from web.field_source import extract_log_fields_for_mapping
        fields = extract_log_fields_for_mapping(None, ["some log"])
        assert fields == []
