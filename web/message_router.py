"""
Chainlit 消息路由器 - 从 chainlit_app.py 提取

本模块处理 @cl.on_message 事件，只做分发，不包含具体逻辑。
增加 per-session asyncio.Lock 防止并发请求竞态修改 SessionState。
"""

import asyncio
import chainlit as cl
from agent.core.tracing import trace_request
from agent.shared.logger import get_logger
from application.model_runtime import ensure_team
from web.file_handlers import handle_file_upload
from web.user_message_handlers import handle_user_message

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
    try:
        # .env 优先：配置可解析即懒初始化 Team；密钥缺失时提示应设置的变量名。
        team = ensure_team(user_session)
    except ValueError as config_error:
        await cl.Message(content=f"⚠️ {config_error}").send()
        return

    # per-session 加锁：同一会话的并发请求串行化，避免状态竞态
    lock = _get_session_lock(user_session)
    if lock.locked():
        logger.info("[LOCK] 会话锁被占用，当前请求将排队等待")
    async with lock:
        # 处理上传的文件
        if message.elements:
            for element in message.elements:
                if hasattr(element, 'type') and element.type == "file":
                    await handle_file_upload(user_session, element)

        # 处理文本消息
        user_text = message.content.strip()
        if user_text:
            await handle_user_message(user_session, team, user_text)
