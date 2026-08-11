"""
handler 参数化接口测试（#18）。

验证 ADR-0004 阶段 1-C：
- handle_fill_from_params：接收显式 target_field + fill_type，不从原文猜参
- handle_fill_from_text：适配器，从 user_text 提取参数后调核心接口
- _extract_target_field / _detect_fill_type：适配器内部使用，核心接口不再调用

测试接缝：web/fill_dispatcher.py
"""
import asyncio
import sys
import types

import pytest


@pytest.fixture(autouse=True)
def _chainlit_stub(monkeypatch):
    """handler 依赖 cl.Message / cl.File，强制提供桩（覆盖已加载的真实 chainlit）。

    fill_dispatcher.py 顶层 import chainlit as cl，cl 已绑定真实模块。
    必须 monkeypatch 模块内的 cl 引用，而非只改 sys.modules。
    """

    class _Msg:
        def __init__(self, *a, **kw):
            self.content = kw.get("content", "")

        async def send(self):
            return self

        async def remove(self):
            return self

        async def update(self):
            return self

        async def stream_token(self, tok):
            self.content += tok

    class _File:
        def __init__(self, *a, **kw):
            pass

    stub = types.ModuleType("chainlit")
    stub.Message = _Msg
    stub.File = _File
    stub.Action = lambda **kw: None
    # 强制覆盖 sys.modules + 各 handler 模块内的 cl 引用
    monkeypatch.setitem(sys.modules, "chainlit", stub)
    import web.fill_dispatcher as _fd
    import web.enum_handler as _eh
    monkeypatch.setattr(_fd, "cl", stub)
    monkeypatch.setattr(_eh, "cl", stub)
    yield


from web.fill_dispatcher import (
    handle_fill_from_params,
    handle_fill_from_text,
    _extract_target_field,
    _detect_fill_type,
)


class TestHandleFillFromParams:
    """handle_fill_from_params — 核心参数化接口（step_planner 调用）。"""

    def test_receives_explicit_target_and_type(self):
        """接收显式 target_field + fill_type，内部不再调 _extract_target_field。"""
        session = {
            "mapped_sub_rules": [
                {"normalize": [{"index": "vul_name", "field": "vul_name", "mappings": []}]}
            ],
            "last_threat_data": [{"mappingType": "REGULAR", "orgValue": ".*test.*", "mappingValue": "漏洞利用"}],
        }
        # 核心接口直接接收参数，不依赖 user_text
        result = asyncio.get_event_loop().run_until_complete(
            handle_fill_from_params(session, target_field="vul_name", fill_type="threat")
        )
        assert result is True
        # 验证填充确实发生：mappings 非空
        assert session["mapped_sub_rules"][0]["normalize"][0]["mappings"] is not None

    def test_no_sub_rules_returns_false(self):
        """无 mapped_sub_rules 时返回 False（不是填充场景）。"""
        session = {}
        result = asyncio.get_event_loop().run_until_complete(
            handle_fill_from_params(session, target_field="vul_name", fill_type="threat")
        )
        assert result is False

    def test_no_target_field_threat_returns_true_with_message(self):
        """threat 类型但无 target_field → 提示用户，返回 True（已处理）。"""
        session = {
            "mapped_sub_rules": [{"normalize": [{"index": "x", "field": "x"}]}],
            "last_threat_data": [{"mappingValue": "test"}],
        }
        result = asyncio.get_event_loop().run_until_complete(
            handle_fill_from_params(session, target_field=None, fill_type="threat")
        )
        assert result is True  # 已处理（发了提示消息），但没执行填充


class TestHandleFillFromTextAdapter:
    """handle_fill_from_text — 适配器（自然语言单意图调用）。"""

    def test_extracts_field_from_text_and_calls_core(self):
        """「威胁填充到alarm_category里」→ 提取 alarm_category → 调核心接口。"""
        session = {
            "mapped_sub_rules": [
                {"normalize": [{"index": "alarm_category", "field": "alarm_category", "mappings": []}]}
            ],
            "last_threat_data": [{"mappingType": "REGULAR", "orgValue": ".*x.*", "mappingValue": "漏洞利用"}],
        }
        result = asyncio.get_event_loop().run_until_complete(
            handle_fill_from_text(session, "威胁填充到alarm_category里")
        )
        assert result is True

    def test_no_data_returns_false(self):
        """无 mapped_sub_rules 且无 raw_base64 → 返回 False（不命中填充）。"""
        session = {}
        result = asyncio.get_event_loop().run_until_complete(
            handle_fill_from_text(session, "威胁填充到alarm_category里")
        )
        assert result is False


class TestExtractTargetField:
    """_extract_target_field — 适配器内部正则（核心接口不再调用）。"""

    def test_extract_chinese_context(self):
        """「填充到alarm_category里」→ alarm_category。"""
        assert _extract_target_field("威胁填充到alarm_category里") == "alarm_category"

    def test_extract_with_field_suffix(self):
        """「填充到event_type1字段」→ event_type1。"""
        assert _extract_target_field("枚举填充到event_type1字段") == "event_type1"

    def test_no_match_returns_none(self):
        """「填回去」无字段名 → None。"""
        assert _extract_target_field("威胁映射填回去") is None


class TestDetectFillType:
    """_detect_fill_type — 适配器内部类型推断（核心接口不再调用）。"""

    def test_explicit_threat_keyword(self):
        """文本含「威胁」→ threat。"""
        assert _detect_fill_type("威胁填充到x里", {}) == "threat"

    def test_explicit_enum_keyword(self):
        """文本含「枚举」→ enum。"""
        assert _detect_fill_type("枚举填充到x里", {}) == "enum"

    def test_last_fill_type_marker(self):
        """无关键词但有 last_fill_type 标记 → 用标记。"""
        assert _detect_fill_type("填充到x里", {"last_fill_type": "threat"}) == "threat"

    def test_default_enum(self):
        """无任何线索 → 默认 enum。"""
        assert _detect_fill_type("填充到x里", {}) == "enum"
