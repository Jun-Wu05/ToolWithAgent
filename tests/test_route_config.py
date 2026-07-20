"""
detect_intent 路由测试 — 覆盖所有分支 + 引导提示。

测试接缝：web/route_config.py 的 detect_intent(user_text, user_session) 纯函数。
Issue 01: detect_intent 引导提示 + 测试基线
"""
import pytest

from web.route_config import detect_intent


class FakeSession:
    """构造测试用 session 状态。"""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

    def get(self, key, default=None):
        return getattr(self, key, default)


# ============================================================
# US-1：mapping 无数据 → general（引导上传）
# ============================================================

class TestMappingNoData:
    """字段映射意图但无数据时，应降级为 general 引导上传。"""

    def test_mapping_no_data_returns_general(self):
        """mapping 关键词 + 无数据 session → general"""
        session = FakeSession(decoded_data=None, decoded_fields=None, simplified_data=None)
        intent, reason = detect_intent("映射", session)
        assert intent == "general"
        assert "无数据" in reason or "引导" in reason

    def test_mapping_no_data_reason_contains_upload_hint(self):
        """reason 应包含具体的上传引导提示（US-1 验收标准）"""
        session = FakeSession(decoded_data=None, decoded_fields=None, simplified_data=None)
        intent, reason = detect_intent("我要字段映射", session)
        assert intent == "general"
        # 引导提示应告诉用户上传什么
        assert "上传" in reason or "Excel" in reason or "Base64" in reason or "文件" in reason

    def test_mapping_no_data_with_explicit_request(self):
        """'我要字段映射' + 无数据 → general"""
        session = FakeSession(decoded_data=None, decoded_fields=None, simplified_data=None)
        intent, reason = detect_intent("我要字段映射", session)
        assert intent == "general"

    def test_mapping_with_data_returns_mapping(self):
        """mapping 关键词 + 有数据 session → mapping"""
        session = FakeSession(
            decoded_data={"test": 1},
            decoded_fields=["src_ip"],
            simplified_data={"fields": ["src_ip"]},
        )
        intent, reason = detect_intent("映射", session)
        assert intent == "mapping"


# ============================================================
# 各意图分支覆盖
# ============================================================

class TestIntentBranches:
    """覆盖 detect_intent 的各意图分支。"""

    def test_threat_returns_threat(self):
        """威胁类型关键词 → threat"""
        session = FakeSession()
        intent, _ = detect_intent("标准化威胁类型", session)
        assert intent == "threat"

    def test_enum_extract_returns_enum(self):
        """枚举提取关键词 → enum"""
        session = FakeSession()
        intent, _ = detect_intent("提取枚举值", session)
        assert intent == "enum"

    def test_log_parser_returns_log_parser(self):
        """日志解析关键词 → log_parser"""
        session = FakeSession()
        intent, _ = detect_intent("日志类型提取", session)
        assert intent == "log_parser"

    def test_general_no_keywords(self):
        """无关键词命中 → general"""
        session = FakeSession()
        intent, reason = detect_intent("你好", session)
        assert intent == "general"


# ============================================================
# 填充动作识别
# ============================================================

class TestFillAction:
    """填充动作识别：返回 fill 交 fill_dispatcher。"""

    def test_fill_returns_fill(self):
        """'填充到xxx' → fill"""
        session = FakeSession(mapped_sub_rules=[{"name": "test"}])
        intent, _ = detect_intent("填充到alarm_category里", session)
        assert intent == "fill"

    def test_fill_no_mapping_data(self):
        """'填充' 无任何数据 → fill（fill_dispatcher 自行判断）"""
        session = FakeSession()
        intent, _ = detect_intent("填充到event_type1", session)
        assert intent == "fill"


# ============================================================
# 消歧规则
# ============================================================

class TestDisambiguation:
    """威胁 vs 映射消歧。"""

    def test_threat_mapping_conflict_ambiguous(self):
        """威胁+映射冲突无法消歧 → ambiguous"""
        session = FakeSession(
            decoded_data={"test": 1},
            decoded_fields=["src_ip"],
            simplified_data={"fields": ["src_ip"]},
        )
        intent, _ = detect_intent("威胁类型字段", session)
        assert intent == "ambiguous"

    def test_mapping_strong_overrides_threat(self):
        """字段映射强信号优先于威胁词"""
        session = FakeSession(
            decoded_data={"test": 1},
            decoded_fields=["src_ip"],
            simplified_data={"fields": ["src_ip"]},
        )
        intent, _ = detect_intent("威胁类型字段映射", session)
        assert intent == "mapping"

    def test_threat_strong_with_action(self):
        """威胁类型强信号+动作词 → threat"""
        session = FakeSession()
        intent, _ = detect_intent("威胁类型标准化", session)
        assert intent == "threat"
