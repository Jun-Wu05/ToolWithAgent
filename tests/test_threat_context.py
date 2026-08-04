"""
威胁映射输入构建测试 — 枚举值结构化注入。

回归背景（2026-07-28）：
  用户「提取枚举值 → 把枚举值做威胁映射」流程中，威胁映射看不到上一步
  提取的枚举值（last_enum_extract_result），只依赖被截断的历史回忆，
  导致 ThreatAgent 无数据可映射。修复：threat 路径显式注入枚举值列表。
"""
import pytest

from web.input_builder import build_llm_input


class FakeSession:
    """构造测试用 session 状态。"""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

    def get(self, key, default=None):
        return getattr(self, key, default)

    def has_decoded_data(self):
        return self.decoded_data is not None or self.decoded_fields is not None


class TestThreatEnumInjection:
    """threat 意图：有枚举提取结果时，注入到 prompt。"""

    def test_threat_with_enum_result_injects_values(self):
        """有 last_enum_extract_result 时，prompt 包含全部枚举值。"""
        session = FakeSession(
            conversation_history=[],
            last_enum_extract_result={
                "field": "ruleCategoryName",
                "value": ["权限绕过", "命令执行", "信息泄露", "远控木马"],
                "unique_count": 4,
            },
        )
        result = build_llm_input("威胁映射", session, intent="threat")
        assert "权限绕过" in result, "枚举值「权限绕过」应注入 threat prompt"
        assert "命令执行" in result, "枚举值「命令执行」应注入 threat prompt"
        assert "远控木马" in result, "枚举值「远控木马」应注入 threat prompt"

    def test_threat_without_enum_result_unchanged(self):
        """无枚举提取结果时，threat prompt 与现状一致（回归）。"""
        session = FakeSession(
            conversation_history=[],
            last_enum_extract_result=None,
        )
        result = build_llm_input("威胁映射", session, intent="threat")
        assert "威胁映射" in result
        assert "待映射的枚举值" not in result, "无枚举结果时不应注入枚举上下文"

    def test_threat_with_empty_enum_values_unchanged(self):
        """枚举结果存在但 value 为空时，不注入（避免空列表污染）。"""
        session = FakeSession(
            conversation_history=[],
            last_enum_extract_result={"field": "x", "value": [], "unique_count": 0},
        )
        result = build_llm_input("威胁映射", session, intent="threat")
        assert "待映射的枚举值" not in result
