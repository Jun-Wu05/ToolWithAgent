"""Excel 数据表格上传契约的回归测试（回归 #78）。"""

import asyncio

import pandas as pd


def _mount_message_capture(monkeypatch, captured):
    """拦截 file_handlers 内的 Chainlit 消息发送。"""
    import web.file_handlers as file_handlers

    class _FakeMessage:
        def __init__(self, content, elements=None, actions=None):
            self.content = content
            self.elements = elements or []
            self.actions = actions or []

        async def send(self):
            captured.append(self.content)

    monkeypatch.setattr(file_handlers.cl, "Message", _FakeMessage)


def test数据表格缺少原始日志列时拒绝并不写入会话(monkeypatch):
    """无"原始日志"列的数据表必须在上传阶段被拒绝，列头不得进入会话。"""
    import web.file_handlers as file_handlers

    captured = []
    _mount_message_capture(monkeypatch, captured)
    monkeypatch.setattr(
        pd,
        "read_excel",
        lambda path: pd.DataFrame(
            {"发生时间": ["2026-08-14"], "事件名称": ["login"], "设备": ["ips"]}
        ),
    )

    session = {}
    asyncio.run(file_handlers._handle_excel_data_table("fake.xlsx", "fake.xlsx", session))

    assert len(captured) == 1
    assert "上传正确的excel，应包含原始日志一列" in captured[0]
    assert session == {}


def test数据表格含原始日志列时正常提取日志行(monkeypatch):
    """含"原始日志"列的数据表保持既有提取行为。"""
    import web.file_handlers as file_handlers

    captured = []
    _mount_message_capture(monkeypatch, captured)
    monkeypatch.setattr(
        pd,
        "read_excel",
        lambda path: pd.DataFrame(
            {
                "发生时间": ["2026-08-14"],
                "原始日志": ['<1>AUDIT: alarm_name="login"'],
                "设备": ["ips"],
            }
        ),
    )

    session = {}
    asyncio.run(file_handlers._handle_excel_data_table("ok.xlsx", "ok.xlsx", session))

    assert len(captured) == 1
    assert "上传正确的excel" not in captured[0]
    assert session["raw_log_lines"] == ['<1>AUDIT: alarm_name="login"']
    assert session["decoded_fields"] == ["发生时间", "原始日志", "设备"]
    assert session["original_log"]
