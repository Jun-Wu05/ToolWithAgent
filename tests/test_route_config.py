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


# ============================================================
# US-3：session_summary 全状态感知（Issue 02）
# ============================================================

class TestSessionSummary:
    """session_summary 应包含当前状态全感知，供 RouterAgent 引导。"""

    def test_empty_session_summary(self):
        """空 session → 空字符串"""
        from web.session_state import SessionState
        sess = SessionState.create_default()
        assert sess.get_session_summary() == ""

    def test_summary_with_file(self):
        """有文件 → 含文件名和字段数"""
        from web.session_state import SessionState
        sess = SessionState()
        sess.decoded_fields = ["src_ip", "dst_ip"]
        sess.uploaded_file_name = "test.xlsx"
        summary = sess.get_session_summary()
        assert "test.xlsx" in summary
        assert "2" in summary

    def test_summary_with_mapped_sub_rules(self):
        """有子规则 → 含子规则信息"""
        from web.session_state import SessionState
        sess = SessionState()
        sess.mapped_sub_rules = [{"name": "r1"}, {"name": "r2"}]
        sess.decoded_fields = ["f1"]
        summary = sess.get_session_summary()
        assert "子规则" in summary
        assert "2" in summary

    def test_summary_with_threat_data(self):
        """有威胁映射 → 含威胁映射信息"""
        from web.session_state import SessionState
        sess = SessionState()
        sess.last_threat_data = [{"a": 1}, {"b": 2}]
        sess.decoded_fields = ["f1"]
        summary = sess.get_session_summary()
        assert "威胁映射" in summary

    def test_summary_with_enum_excel(self):
        """有枚举映射表 → 含枚举映射表信息"""
        from web.session_state import SessionState
        sess = SessionState()
        sess.enum_excel_path = "/tmp/enum.xlsx"
        sess.decoded_fields = ["f1"]
        summary = sess.get_session_summary()
        assert "枚举" in summary


# ============================================================
# US-2：完成后下一步提示（Issue 03）
# ============================================================

class TestNextStepHint:
    """_get_next_step_hint 根据 session 状态返回下一步操作建议。"""

    def test_hint_after_mapping_with_data(self):
        """字段映射完成 → 提示枚举提取或威胁映射"""
        from web.response_handler import _get_next_step_hint
        from web.session_state import SessionState
        sess = SessionState()
        sess.last_mapping_data = [{"原始字段名": "src_ip", "系统属性名称": "源地址"}]
        sess.mapped_sub_rules = [{"name": "r1"}]
        hint = _get_next_step_hint(sess)
        assert hint  # 非空
        assert "枚举" in hint or "威胁" in hint

    def test_hint_after_threat_mapping(self):
        """威胁映射完成 → 提示填充"""
        from web.response_handler import _get_next_step_hint
        from web.session_state import SessionState
        sess = SessionState()
        sess.last_threat_data = [{"orgValue": "xss", "mappingValue": "XSS"}]
        sess.mapped_sub_rules = [{"name": "r1"}]
        hint = _get_next_step_hint(sess)
        assert hint
        assert "填充" in hint

    def test_hint_after_enum_extract(self):
        """枚举提取完成 → 提示填充或威胁映射"""
        from web.response_handler import _get_next_step_hint
        from web.session_state import SessionState
        sess = SessionState()
        sess.last_enum_extract_result = {"field": "content", "value": ["a", "b"]}
        sess.mapped_sub_rules = [{"name": "r1"}]
        hint = _get_next_step_hint(sess)
        assert hint
        assert "填充" in hint or "威胁" in hint

    def test_hint_empty_session(self):
        """空 session → 提示上传"""
        from web.response_handler import _get_next_step_hint
        from web.session_state import SessionState
        sess = SessionState()
        hint = _get_next_step_hint(sess)
        assert hint
        assert "上传" in hint
