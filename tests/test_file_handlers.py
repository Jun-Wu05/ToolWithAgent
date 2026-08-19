"""Excel 数据表格上传契约的回归测试（回归 #78）。"""

import asyncio
from types import SimpleNamespace

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


def test有效配置上传原子替换旧日志数据集状态(monkeypatch):
    """新 Base64/TXT 提交后，旧日志数据集及其附件和派生结果全部失效。"""
    import web.file_handlers as file_handlers
    from contracts.session_facts import build_session_facts
    from web.session_state import SessionState

    captured = []
    _mount_message_capture(monkeypatch, captured)
    monkeypatch.setattr(file_handlers, "read_element_content", lambda element: "encoded")
    monkeypatch.setattr(file_handlers, "get_element_file_name", lambda element: element.name)
    monkeypatch.setattr(
        file_handlers,
        "decode_file_content",
        lambda content: {
            "status": "success",
            "decoded_json": {
                "name": "new-rule",
                "normalize": [{"index": "new_index", "field": "", "mappings": []}],
            },
            "fields": ["new_index"],
            "original_log": [],
            "decoded_text": '{"name":"new-rule"}',
            "field_count": 1,
        },
    )

    session = SessionState(
        team=object(),
        current_provider="deepseek",
        api_key="configured",
        model_name="model-a",
        decoded_data=[{"原始日志": "old"}],
        decoded_fields=["old_field"],
        original_log=["old log"],
        raw_log_lines=["old log"],
        log_classification={"types": ["IPS"]},
        mapped_sub_rules=[{"normalize": [{"index": "old_field"}]}],
        last_mapping_data=[{"原始字段": "old_field"}],
        batch_mapping_results=[{"rule_name": "old"}],
        sub_rule_mapping_results=[{"rule_name": "old"}],
        last_enum_extract_result={"field": "old_field", "value": ["old"]},
        last_threat_data=[{"orgValue": "old"}],
        excel_data=b"old",
        excel_filename="old.xlsx",
        enum_excel_path="old-enum.xlsx",
        enum_preview=[{"目标字段": "old_field"}],
        conversation_history=[{"role": "user", "content": "处理旧文件"}],
    )

    asyncio.run(
        file_handlers.handle_file_upload(
            session,
            SimpleNamespace(name="new.txt"),
        )
    )

    facts = build_session_facts(session)
    assert facts.has_logs is False
    assert facts.has_log_classification is False
    assert facts.available_fields == ("new_index",)
    assert facts.available_config_refs == ("session.decoded_config",)
    assert session.decoded_data["name"] == "new-rule"
    assert session.raw_log_lines is None
    assert session.log_classification is None
    assert session.mapped_sub_rules is None
    assert session.last_mapping_data is None
    assert session.batch_mapping_results is None
    assert session.sub_rule_mapping_results is None
    assert session.last_enum_extract_result is None
    assert session.last_threat_data is None
    assert session.excel_data is None
    assert session.excel_filename is None
    assert session.enum_excel_path is None
    assert session.enum_preview is None
    assert session.conversation_history == []
    assert session.team is not None
    assert session.current_provider == "deepseek"
    assert session.api_key == "configured"
    assert session.model_name == "model-a"


def test有效日志表原子替换旧配置数据集状态(monkeypatch):
    """新日志 Excel 提交后，旧配置引用、附件和派生结果对称失效。"""
    import web.file_handlers as file_handlers
    from contracts.session_facts import build_session_facts
    from web.session_state import SessionState

    captured = []
    _mount_message_capture(monkeypatch, captured)
    monkeypatch.setattr(
        pd,
        "read_excel",
        lambda path: pd.DataFrame(
            {
                "发生时间": ["2026-08-19"],
                "原始日志": ['<1>IPS: src_ip="10.0.0.1"'],
                "设备": ["ips"],
            }
        ),
    )
    session = SessionState(
        decoded_data={
            "name": "old-config",
            "normalize": [{"index": "old_index", "field": "old_field"}],
        },
        decoded_fields=["old_index"],
        raw_base64="old-encoded",
        mapped_sub_rules=[{"normalize": [{"index": "old_index"}]}],
        log_classification={"types": ["AUDIT"]},
        enum_excel_path="old-enum.xlsx",
        enum_preview=[{"目标字段": "old_field"}],
        conversation_history=[{"role": "assistant", "content": "旧配置"}],
    )

    asyncio.run(file_handlers._handle_excel_data_table("new.xlsx", "new.xlsx", session))

    facts = build_session_facts(session)
    assert facts.has_logs is True
    # 日志 Excel 也会形成 decoded_data；是否存在可执行配置以引用列表为准。
    assert facts.has_decoded_config is True
    assert facts.has_log_classification is False
    assert facts.has_mapped_sub_rules is False
    assert facts.available_config_refs == ()
    assert "old_index" not in facts.available_fields
    assert session.raw_log_lines == ['<1>IPS: src_ip="10.0.0.1"']
    assert session.raw_base64 is None
    assert session.mapped_sub_rules is None
    assert session.log_classification is None
    assert session.enum_excel_path is None
    assert session.enum_preview is None
    assert session.conversation_history == []


def test无效配置上传保持当前有效会话(monkeypatch):
    """配置解码失败时不得提前清除旧主数据、附件或派生结果。"""
    import web.file_handlers as file_handlers
    from web.session_state import SessionState

    captured = []
    _mount_message_capture(monkeypatch, captured)
    monkeypatch.setattr(file_handlers, "read_element_content", lambda element: "invalid")
    monkeypatch.setattr(
        file_handlers,
        "decode_file_content",
        lambda content: {"status": "error", "error_message": "invalid base64"},
    )
    session = SessionState(
        decoded_data={"name": "current"},
        decoded_fields=["current_field"],
        mapped_sub_rules=[{"normalize": [{"index": "current_field"}]}],
        enum_excel_path="current-enum.xlsx",
        enum_preview=[{"目标字段": "current_field"}],
        conversation_history=[{"role": "user", "content": "当前文件"}],
    )

    asyncio.run(file_handlers.handle_file_upload(session, SimpleNamespace(name="bad.txt")))

    assert session.decoded_data == {"name": "current"}
    assert session.decoded_fields == ["current_field"]
    assert session.mapped_sub_rules == [{"normalize": [{"index": "current_field"}]}]
    assert session.enum_excel_path == "current-enum.xlsx"
    assert session.enum_preview == [{"目标字段": "current_field"}]
    assert session.conversation_history == [{"role": "user", "content": "当前文件"}]
    assert captured == ["❌ 解码失败：invalid base64"]


def test无效日志表上传保持当前有效会话(monkeypatch):
    """缺少原始日志列的 Excel 在提交前拒绝，旧会话完整保留。"""
    import web.file_handlers as file_handlers
    from web.session_state import SessionState

    captured = []
    _mount_message_capture(monkeypatch, captured)
    monkeypatch.setattr(
        pd,
        "read_excel",
        lambda path: pd.DataFrame({"发生时间": ["2026-08-19"], "设备": ["ips"]}),
    )
    session = SessionState(
        decoded_data={"name": "current"},
        decoded_fields=["current_field"],
        log_classification={"types": ["IPS"]},
        enum_excel_path="current-enum.xlsx",
        enum_preview=[{"目标字段": "current_field"}],
        conversation_history=[{"role": "assistant", "content": "当前结果"}],
    )

    asyncio.run(file_handlers._handle_excel_data_table("bad.xlsx", "bad.xlsx", session))

    assert session.decoded_data == {"name": "current"}
    assert session.decoded_fields == ["current_field"]
    assert session.log_classification == {"types": ["IPS"]}
    assert session.enum_excel_path == "current-enum.xlsx"
    assert session.enum_preview == [{"目标字段": "current_field"}]
    assert session.conversation_history == [{"role": "assistant", "content": "当前结果"}]
    assert len(captured) == 1
    assert "上传正确的excel，应包含原始日志一列" in captured[0]
