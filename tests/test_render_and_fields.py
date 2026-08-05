"""
render_log_parser_result 测试 — real_samples 含 | 时不应被 Markdown 表格截断。

问题回归：KV 日志行 uuid=xxx|name=yyy|... 在表格 `| 特征值 | 样例 |` 中，
  样例的 | 被当列分隔符，只显示第一个 | 之前的内容。
  修复：样例改用代码块展示，| 不再被解析。
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
