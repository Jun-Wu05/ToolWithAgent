"""
step_planner 测试 — PLAN 标记解析 + 步骤队列管理。

测试接缝：web/step_planner.py
- parse_plan_marker: 纯函数，解析 [PLAN:threat|fill] → ["threat", "fill"]
- pop_next_step / has_pending_steps: 步骤队列管理
"""
import pytest

from web.step_planner import parse_plan_marker, pop_next_step, has_pending_steps


class FakeSession:
    """支持 pending_steps 读写（模拟 SessionState 的 get/__setitem__ 行为）。"""
    def __init__(self, pending_steps=None):
        self.pending_steps = pending_steps

    def get(self, key, default=None):
        return getattr(self, key, default)

    def __setitem__(self, key, value):
        setattr(self, key, value)


class TestParsePlanMarker:
    """parse_plan_marker 标记解析。"""

    def test_parse_two_steps(self):
        """[PLAN:threat|fill] → ["threat", "fill"]"""
        content = "我将分两步处理。\n\n[PLAN:threat|fill]"
        result = parse_plan_marker(content)
        assert result == ["threat", "fill"]

    def test_parse_three_steps(self):
        """[PLAN:mapping|enum|threat] → 三个步骤"""
        content = "[PLAN:mapping|enum|threat]"
        assert parse_plan_marker(content) == ["mapping", "enum", "threat"]

    def test_parse_single_step(self):
        """单步骤也能解析（虽然 skill 通常用于多步，但单步也合法）。"""
        content = "处理中\n[PLAN:threat]"
        assert parse_plan_marker(content) == ["threat"]

    def test_no_marker_returns_none(self):
        """无标记返回 None。"""
        assert parse_plan_marker("普通回复，无计划标记") is None

    def test_marker_with_surrounding_text(self):
        """标记前后有大量文本仍能提取。"""
        content = (
            "根据您的请求，我将先执行威胁映射，再用结果填充子规则。\n"
            "这是一个复合操作，已分解为步骤。\n\n"
            "[PLAN:threat|fill]\n\n"
            "系统将自动按序执行。"
        )
        assert parse_plan_marker(content) == ["threat", "fill"]

    def test_invalid_step_type_still_extracted(self):
        """未知步骤类型也会被提取（执行时由 execute_step 处理无效类型）。"""
        assert parse_plan_marker("[PLAN:unknown_step]") == ["unknown_step"]


class TestStepQueue:
    """步骤队列管理（pop_next_step / has_pending_steps）。"""

    def test_has_pending_steps_true(self):
        """有待执行步骤时返回 True。"""
        session = FakeSession(pending_steps=["threat", "fill"])
        assert has_pending_steps(session) is True

    def test_has_pending_steps_false_empty(self):
        """无步骤时返回 False。"""
        session = FakeSession(pending_steps=[])
        assert has_pending_steps(session) is False

    def test_has_pending_steps_false_none(self):
        """pending_steps 为 None 时返回 False。"""
        session = FakeSession(pending_steps=None)
        assert has_pending_steps(session) is False

    def test_pop_next_step_returns_first_and_removes(self):
        """pop_next_step 返回第一个步骤并从队列移除。"""
        session = FakeSession(pending_steps=["threat", "fill", "enum"])
        step = pop_next_step(session)
        assert step == "threat"
        assert session.pending_steps == ["fill", "enum"]

    def test_pop_next_step_empty_returns_none(self):
        """空队列 pop 返回 None。"""
        session = FakeSession(pending_steps=[])
        assert pop_next_step(session) is None
