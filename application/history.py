"""会话对话历史的截断、格式化与清理。"""

from __future__ import annotations

from typing import Any

from agent.shared.logger import get_logger
from contracts.planner_models import ConversationTurn
from application.session_state import SessionState

logger = get_logger("history_store")

MAX_ENTRY_CHARS = 1500
DEFAULT_HISTORY_ROUNDS = 5
DEFAULT_HISTORY_MAX_CHARS = 6000


def append_history(session: SessionState, role: str, content: str) -> None:
    """追加一轮历史并保持既有单条截断策略。"""
    history = session.conversation_history or []
    truncated = (
        content[:MAX_ENTRY_CHARS] + "...(已截断)"
        if len(content) > MAX_ENTRY_CHARS
        else content
    )
    history.append({"role": role, "content": truncated})
    session.conversation_history = history
    logger.debug("[HISTORY] 追加 %s（当前 %s 条）", role, len(history))


def typed_conversation_history(session: SessionState) -> list[ConversationTurn]:
    """把会话历史转换为 Planner 接受的受限类型。"""
    history = session.conversation_history or []
    typed: list[ConversationTurn] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str):
            continue
        normalized = content.strip()[:2000]
        if normalized:
            typed.append(ConversationTurn(role=role, content=normalized))
    return typed


def format_history_for_prompt(
    session: SessionState,
    n: int = DEFAULT_HISTORY_ROUNDS,
    max_chars: int = DEFAULT_HISTORY_MAX_CHARS,
) -> str:
    """将最近 n 轮历史按既有滑动窗口格式化为文本。"""
    history = session.conversation_history or []
    if not history:
        return ""
    recent = history[-(n * 2) :]
    lines: list[str] = []
    total = 0
    for entry in reversed(recent):
        role = entry.get("role", "")
        content = entry.get("content", "")
        label = "用户" if role == "user" else "助手"
        line = f"[{label}] {content}"
        if total + len(line) > max_chars:
            lines.append("...(更早的对话已省略)")
            break
        lines.append(line)
        total += len(line)
    lines.reverse()
    return "💬 最近对话：\n" + "\n".join(lines)


def clear_history(session: SessionState) -> None:
    """清空当前会话历史。"""
    session.conversation_history = []
    logger.info("[HISTORY] 对话历史已清空")
