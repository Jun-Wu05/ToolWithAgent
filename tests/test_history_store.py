"""
history_store 截断阈值与滑动窗口回归测试。

回归背景（issue #6）：
  MAX_ENTRY_CHARS 原 500，枚举值列表（4个值+说明）常超 500 被截断，
  后续威胁映射步骤看不到完整列表。放宽到 1500。
  DEFAULT_HISTORY_MAX_CHARS 原 2000，与单条 1500 几乎相等，
  1 条满长记录吃满总窗口导致多轮退化。同步放大到 6000。
"""
from application.history import (
    MAX_ENTRY_CHARS,
    DEFAULT_HISTORY_MAX_CHARS,
    DEFAULT_HISTORY_ROUNDS,
    append_history,
    format_history_for_prompt,
)
from factories import make_session_state


class TestHistoryEntryTruncation:
    """单条 content 截断阈值。"""

    def test_max_entry_chars_is_1500(self):
        """MAX_ENTRY_CHARS 应为 1500（原 500 过小，截断枚举值列表）。"""
        assert MAX_ENTRY_CHARS == 1500

    def test_content_under_limit_not_truncated(self):
        """短于阈值的 content 原样保留。"""
        s = make_session_state()
        append_history(s, "user", "短消息")
        assert s.conversation_history[-1]["content"] == "短消息"

    def test_content_at_limit_not_truncated(self):
        """恰好等于阈值的 content 不被截断。"""
        s = make_session_state()
        content = "x" * MAX_ENTRY_CHARS
        append_history(s, "assistant", content)
        assert s.conversation_history[-1]["content"] == content

    def test_content_over_limit_truncated(self):
        """超阈值的 content 被截断到阈值长度 + 截断标记。"""
        s = make_session_state()
        content = "x" * (MAX_ENTRY_CHARS + 500)
        append_history(s, "assistant", content)
        stored = s.conversation_history[-1]["content"]
        # 截断后应含截断标记，且不超过阈值 + 标记长度
        assert "已截断" in stored
        assert len(stored) <= MAX_ENTRY_CHARS + 50  # 阈值 + 截断标记余量


class TestHistoryWindowBudget:
    """总窗口预算与多轮容纳能力。"""

    def test_total_window_is_6000(self):
        """DEFAULT_HISTORY_MAX_CHARS 应为 6000（原 2000 与单条 1500 冲突）。"""
        assert DEFAULT_HISTORY_MAX_CHARS == 6000

    def test_single_full_entry_does_not_eat_window(self):
        """1 条满长记录（1500）不应吃满总窗口，应还能容纳更多轮次。

        回归：原总窗口 2000 时，1 条 1500 记录占 75%，滑动窗口贪心累加
        后实际只剩 1-2 条可见，多轮语义链断裂。
        """
        s = make_session_state()
        # 写入 1 条满长 assistant 记录 + 配对 user 记录 + 第二轮
        full_content = "y" * MAX_ENTRY_CHARS
        append_history(s, "user", "提取枚举值")
        append_history(s, "assistant", full_content)
        append_history(s, "user", "做威胁映射")
        append_history(s, "assistant", "映射结果")

        formatted = format_history_for_prompt(s)
        # 总窗口 6000 应能容纳至少 2 整轮（含满长记录），不应出现"更早的对话已省略"
        assert "更早的对话已省略" not in formatted, (
            "总窗口过小：1 条满长记录吃满窗口，多轮被截断"
        )
        # 第一轮的 user 记录应可见（证明不只显示了最后 1-2 条）
        assert "提取枚举值" in formatted
