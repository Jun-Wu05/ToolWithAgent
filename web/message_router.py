"""
Chainlit 消息路由器 - 从 chainlit_app.py 提取

本模块处理 @cl.on_message 事件，只做分发，不包含具体逻辑。
增加 per-session asyncio.Lock 防止并发请求竞态修改 SessionState。
"""

import asyncio
import chainlit as cl
from agent.core.tracing import trace_request
from agent.shared.logger import get_logger

logger = get_logger("message_router")


# per-session 锁池：同一会话的请求串行执行，避免并发竞态
# key 用 id(user_session)（SessionState 实例 per-session 唯一）
_session_locks: dict[int, asyncio.Lock] = {}


def _get_session_lock(session_obj: object) -> asyncio.Lock:
    """获取（或创建）指定会话的 asyncio.Lock。"""
    key = id(session_obj)
    if key not in _session_locks:
        _session_locks[key] = asyncio.Lock()
    return _session_locks[key]


# 延迟导入避免循环依赖
_file_handlers = None
_user_message_handlers = None


def get_file_handlers():
    """延迟导入 file_handlers 避免循环依赖"""
    global _file_handlers
    if _file_handlers is None:
        from web import file_handlers
        _file_handlers = file_handlers
    return _file_handlers


def get_user_message_handlers():
    """延迟导入 user_message_handlers 避免循环依赖"""
    global _user_message_handlers
    if _user_message_handlers is None:
        from web import user_message_handlers
        _user_message_handlers = user_message_handlers
    return _user_message_handlers


@cl.on_message
@trace_request("user_request")
async def on_message(message: cl.Message):
    """
    处理用户消息 - 纯UI层

    职责：
    1. 分发文件上传到 file_handlers
    2. 分发文本消息到 user_message_handlers
    3. per-session 加锁，保证同一会话请求串行（防并发竞态）
    """
    user_session = cl.user_session.get("user_session")
    team = user_session.team if user_session else None

    if team is None:
        await cl.Message(content="⚠️ Team未初始化，请刷新页面重新开始").send()
        return

    # per-session 加锁：同一会话的并发请求串行化，避免状态竞态
    lock = _get_session_lock(user_session)
    if lock.locked():
        logger.info("[LOCK] 会话锁被占用，当前请求将排队等待")
    async with lock:
        # 处理上传的文件
        if message.elements:
            file_handlers = get_file_handlers()
            for element in message.elements:
                if hasattr(element, 'type') and element.type == "file":
                    await file_handlers.handle_file_upload(user_session, element)

        # 处理文本消息
        user_text = message.content.strip()
        if user_text:
            user_message_handlers = get_user_message_handlers()
            await user_message_handlers.handle_user_message(user_session, team, user_text)