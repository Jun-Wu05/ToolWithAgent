"""Issue #171：Agno 日志桥安装状态与启动 seam 回归。"""

from __future__ import annotations

import asyncio
import logging


def test_setup_agno_logging_bridge首次安装并保持幂等返回与handler数量(monkeypatch) -> None:
    import web.llm_client as llm_client

    logger_names = ("agno", "agno.agent", "agno.team", "agno.models", "")
    original_handlers = {
        name: list(logging.getLogger(name).handlers) for name in logger_names
    }
    monkeypatch.setattr(llm_client, "_agno_bridge_installed", False)
    monkeypatch.setattr(llm_client.ModelConfig, "get_model_id", lambda: "test-model")

    try:
        first = llm_client.setup_agno_logging_bridge()
        second = llm_client.setup_agno_logging_bridge()

        assert isinstance(first, logging.Handler)
        assert second is None
        assert all(
            sum(handler is first for handler in logging.getLogger(name).handlers) == 1
            for name in logger_names
        )
    finally:
        for name, handlers in original_handlers.items():
            logging.getLogger(name).handlers[:] = handlers


def test_on_chat_start每次最先调用幂等日志桥且不持有安装状态(monkeypatch) -> None:
    import web.settings_handler as settings_handler
    import web.start_handler as start_handler

    events = []
    monkeypatch.setattr(
        start_handler,
        "setup_agno_logging_bridge",
        lambda: events.append("bridge"),
    )
    monkeypatch.setattr(
        start_handler.SessionState,
        "create_default",
        lambda: events.append("session") or object(),
    )

    class UserSession:
        def set(self, key, value) -> None:
            events.append(("session-set", key))

    class Thread:
        def __init__(self, *, target, daemon, name) -> None:
            self.name = name

        def start(self) -> None:
            events.append("thread")

    class ChatSettings:
        def __init__(self, widgets) -> None:
            self.widgets = widgets

        async def send(self) -> None:
            events.append("settings")

    class Message:
        def __init__(self, *, content) -> None:
            self.content = content

        async def send(self) -> None:
            events.append("message")

    monkeypatch.setattr(start_handler.threading, "Thread", Thread)
    monkeypatch.setattr(settings_handler, "build_settings_widgets", lambda: [])
    monkeypatch.setattr(start_handler.cl, "user_session", UserSession())
    monkeypatch.setattr(start_handler.cl, "ChatSettings", ChatSettings)
    monkeypatch.setattr(start_handler.cl, "Message", Message)

    asyncio.run(start_handler.on_chat_start())
    asyncio.run(start_handler.on_chat_start())

    assert events.count("bridge") == 2
    assert events[0] == "bridge"
    second_start = events.index("bridge", 1)
    assert events[second_start + 1] == "session"
