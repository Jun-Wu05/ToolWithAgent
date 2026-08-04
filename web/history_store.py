"""
对话历史管理 — 自定义轻量记忆（不依赖 Agno session）

提供:
- append_history(session, role, content)          追加一轮对话
- format_history_for_prompt(session, n, max_chars) 拼成 prompt 文本
- clear_history(session)                           清空历史

设计原则:
- 历史存在 SessionState.conversation_history（天然 per-session 隔离）
- 单条 content 截断（防大映射结果撑爆历史）
- format 时从最新向前取，累计不超 max_chars（滑动窗口）
- Team 保持无状态单例，历史由 build_llm_input 拼进 prompt
"""
from __future__ import annotations

from typing import Any, List, Dict

from agent.shared.logger import get_logger

logger = get_logger("history_store")

# 单条历史记录的 content 最大字符数（超长截断，防映射结果 JSON 撑爆历史）
MAX_ENTRY_CHARS = 500
# 默认取最近几轮
DEFAULT_HISTORY_ROUNDS = 5
# 默认历史拼入 prompt 的最大字符数
DEFAULT_HISTORY_MAX_CHARS = 2000


def append_history(session: Any, role: str, content: str) -> None:
    """追加一轮对话到 session.conversation_history。

    Args:
        session: SessionState 实例（必须有 conversation_history 字段）
        role: "user" | "assistant"
        content: 消息文本（超长自动截断到 MAX_ENTRY_CHARS）
    """
    history: List[Dict[str, Any]] = getattr(session, "conversation_history", None) or []
    truncated = content[:MAX_ENTRY_CHARS] + "...(已截断)" if len(content) > MAX_ENTRY_CHARS else content
    history.append({"role": role, "content": truncated})
    # SessionState 是 dataclass，直接赋值生效
    if hasattr(session, "conversation_history"):
        session.conversation_history = history
    logger.debug(f"[HISTORY] 追加 {role}（当前 {len(history)} 条）")


def format_history_for_prompt(
    session: Any,
    n: int = DEFAULT_HISTORY_ROUNDS,
    max_chars: int = DEFAULT_HISTORY_MAX_CHARS,
) -> str:
    """将最近 n 轮对话格式化为 prompt 文本。

    从最新向前取，累计字符数不超过 max_chars（滑动窗口裁剪）。

    Returns:
        格式化后的历史文本（无历史时返回空字符串）：
        💬 最近对话：
        [用户] 帮我映射字段
        [助手] 已完成51个字段映射...
    """
    history: List[Dict[str, Any]] = getattr(session, "conversation_history", None) or []
    if not history:
        return ""

    # 取最近 n*2 条（一轮=user+assistant）
    recent = history[-(n * 2):]

    # 从最新向前累计，超 max_chars 则停止
    lines: List[str] = []
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


def clear_history(session: Any) -> None:
    """清空对话历史（数据清空时调用）。"""
    if hasattr(session, "conversation_history"):
        session.conversation_history = []
        logger.info("[HISTORY] 对话历史已清空")
