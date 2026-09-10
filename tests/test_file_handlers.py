"""Excel 数据表格上传契约的回归测试（回归 #78）。"""

import asyncio
from types import SimpleNamespace

import pandas as pd
from openpyxl import Workbook

from contracts.planner_models import (
    EnumValuesArtifact,
    ThreatMappingArtifact,
    ThreatMappingRow,
)
from contracts.session_artifacts import EnumArtifactSlot, ThreatArtifactSlot


def _referenceable_artifact_slots():
    """构造用于文件生命周期断言的两类成功产物。"""
    enum_slot = EnumArtifactSlot(
        artifact=EnumValuesArtifact(
            values=("attack",), item_count=1, field="current_field"
        ),
        source_field="current_field",
    )
    threat_slot = ThreatArtifactSlot(
        artifact=ThreatMappingArtifact(
            mappings=(
                ThreatMappingRow.model_validate(
                    {
                        "mappingType": "EQUAL",
                        "orgValue": "attack",
                        "mappingValue": "恶意活动",
                    }
                ),
            ),
            item_count=1,
            source_field="current_field",
        ),
        source_field="current_field",
    )
    return enum_slot, threat_slot


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
    monkeypatch.setattr(file_handlers, "clear_primary_report_anchor", lambda: None)


def _write_enum_workbook(path, sheets):
    """写入真实多 Sheet 枚举工作簿，供上传全链路测试使用。"""
    workbook = Workbook()
    first = True
    for sheet_name, rows in sheets.items():
        worksheet = workbook.active if first else workbook.create_sheet()
        first = False
        worksheet.title = sheet_name
        worksheet.append(["mappingType", "orgValue", "mappingValue"])
        for row in rows:
            worksheet.append(row)
    workbook.save(path)
    workbook.close()


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
    cleared = []
    monkeypatch.setattr(
        file_handlers, "clear_primary_report_anchor", lambda: cleared.append(True)
    )
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
    assert cleared == [True]


def test有效配置上传原子替换旧日志数据集状态(monkeypatch):
    """新 Base64/TXT 提交后，旧日志数据集及其附件和派生结果全部失效。"""
    import web.file_handlers as file_handlers
    from application.session_projection import build_session_facts
    from application.session_state import SessionState

    captured = []
    _mount_message_capture(monkeypatch, captured)
    monkeypatch.setattr(file_handlers, "read_element_content", lambda element: "encoded")
    monkeypatch.setattr(file_handlers, "get_element_file_name", lambda element: element.name)
    monkeypatch.setattr(
        file_handlers,
        "simple_decode",
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
        sub_rule_mapping_results=[{"rule_name": "old"}],
        last_enum_extract_result={"field": "old_field", "value": ["old"]},
        last_threat_data=[{"orgValue": "old"}],
        excel_data=b"old",
        excel_filename="old.xlsx",
        enum_excel_path="old-enum.xlsx",
        enum_preview=[{"目标字段": "old_field"}],
        enum_mapping_sheets={"old_field": [{"orgValue": "old"}]},
        enum_fill_contributions={
            "session.decoded_config": {"old_field": [{"mapping": {"orgValue": "old"}}]}
        },
        stale_enum_config_refs={"session.decoded_config"},
        enum_pending_refills={"session.decoded_config": {"old_field"}},
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
    assert session.sub_rule_mapping_results is None
    assert session.last_enum_extract_result is None
    assert session.last_threat_data is None
    assert session.excel_data is None
    assert session.excel_filename is None
    assert session.enum_excel_path is None
    assert session.enum_preview is None
    assert session.enum_mapping_sheets == {}
    assert session.enum_fill_contributions == {}
    assert session.stale_enum_config_refs == set()
    assert session.enum_pending_refills == {}
    assert session.conversation_history == []
    assert session.team is not None
    assert session.current_provider == "deepseek"
    assert session.api_key == "configured"
    assert session.model_name == "model-a"


def test真实base64上传贯通application解码原子提交与既有反馈(monkeypatch):
    """最高层上传接缝使用真实解码器，并保持 Session 与用户消息契约。"""
    import base64
    import json

    import web.file_handlers as file_handlers
    from application.session_state import SessionState

    captured = []
    _mount_message_capture(monkeypatch, captured)
    payload = {
        "name": "new-rule",
        "normalize": [
            {"index": "src_ip"},
            {"index": "original_log", "result": ["src_ip=1.1.1.1"]},
        ],
    }
    encoded = base64.b64encode(
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    monkeypatch.setattr(file_handlers, "read_element_content", lambda element: encoded)
    enum_slot, threat_slot = _referenceable_artifact_slots()
    session = SessionState(
        decoded_data={"name": "old-rule"},
        enum_excel_path="old.xlsx",
        latest_enum_artifact=enum_slot,
        latest_threat_artifact=threat_slot,
    )

    asyncio.run(
        file_handlers.handle_file_upload(session, SimpleNamespace(name="new.txt"))
    )

    assert session.decoded_data == payload
    assert session.decoded_fields == ["src_ip", "original_log"]
    assert session.original_log == ["src_ip=1.1.1.1"]
    assert session.raw_base64 == encoded
    assert session.enum_excel_path is None
    assert session.latest_enum_artifact is None
    assert session.latest_threat_artifact is None
    assert captured == [
        """✅ **文件解码成功！**

📊 **字段数量**：2 个
📊 **日志行数**：1 行

💡 如需处理其他文件，请输入 **"清空数据"** 或 **"切换文件"** 快速重置
现在可以进行字段映射、威胁类型、枚举提取等操作。"""
    ]


def test有效日志表原子替换旧配置数据集状态(monkeypatch):
    """新日志 Excel 提交后，旧配置引用、附件和派生结果对称失效。"""
    import web.file_handlers as file_handlers
    from application.session_projection import build_session_facts
    from application.session_state import SessionState

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
        enum_mapping_sheets={"old_field": [{"orgValue": "old"}]},
        enum_fill_contributions={
            "session.decoded_config": {"old_field": [{"mapping": {"orgValue": "old"}}]}
        },
        stale_enum_config_refs={"session.decoded_config"},
        enum_pending_refills={"session.decoded_config": {"old_field"}},
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
    assert session.enum_mapping_sheets == {}
    assert session.enum_fill_contributions == {}
    assert session.stale_enum_config_refs == set()
    assert session.enum_pending_refills == {}
    assert session.conversation_history == []


def test无效配置上传保持当前有效会话(monkeypatch):
    """配置解码失败时不得提前清除旧主数据、附件或派生结果。"""
    import web.file_handlers as file_handlers
    from application.session_state import SessionState

    captured = []
    _mount_message_capture(monkeypatch, captured)
    monkeypatch.setattr(file_handlers, "read_element_content", lambda element: "invalid")
    monkeypatch.setattr(
        file_handlers,
        "simple_decode",
        lambda content: {"status": "error", "error_message": "invalid base64"},
    )
    enum_slot, threat_slot = _referenceable_artifact_slots()
    session = SessionState(
        decoded_data={"name": "current"},
        decoded_fields=["current_field"],
        mapped_sub_rules=[{"normalize": [{"index": "current_field"}]}],
        enum_excel_path="current-enum.xlsx",
        enum_preview=[{"目标字段": "current_field"}],
        latest_enum_artifact=enum_slot,
        latest_threat_artifact=threat_slot,
        conversation_history=[{"role": "user", "content": "当前文件"}],
    )

    asyncio.run(file_handlers.handle_file_upload(session, SimpleNamespace(name="bad.txt")))

    assert session.decoded_data == {"name": "current"}
    assert session.decoded_fields == ["current_field"]
    assert session.mapped_sub_rules == [{"normalize": [{"index": "current_field"}]}]
    assert session.enum_excel_path == "current-enum.xlsx"
    assert session.enum_preview == [{"目标字段": "current_field"}]
    assert session.latest_enum_artifact == enum_slot
    assert session.latest_threat_artifact == threat_slot
    assert session.conversation_history == [{"role": "user", "content": "当前文件"}]
    assert captured == ["❌ 解码失败：invalid base64"]


def test无效日志表上传保持当前有效会话(monkeypatch):
    """缺少原始日志列的 Excel 在提交前拒绝，旧会话完整保留。"""
    import web.file_handlers as file_handlers
    from application.session_state import SessionState

    captured = []
    _mount_message_capture(monkeypatch, captured)
    monkeypatch.setattr(
        pd,
        "read_excel",
        lambda path: pd.DataFrame({"发生时间": ["2026-08-19"], "设备": ["ips"]}),
    )
    enum_slot, threat_slot = _referenceable_artifact_slots()
    session = SessionState(
        decoded_data={"name": "current"},
        decoded_fields=["current_field"],
        log_classification={"types": ["IPS"]},
        enum_excel_path="current-enum.xlsx",
        enum_preview=[{"目标字段": "current_field"}],
        latest_enum_artifact=enum_slot,
        latest_threat_artifact=threat_slot,
        conversation_history=[{"role": "assistant", "content": "当前结果"}],
    )

    asyncio.run(file_handlers._handle_excel_data_table("bad.xlsx", "bad.xlsx", session))

    assert session.decoded_data == {"name": "current"}
    assert session.decoded_fields == ["current_field"]
    assert session.log_classification == {"types": ["IPS"]}
    assert session.enum_excel_path == "current-enum.xlsx"
    assert session.enum_preview == [{"目标字段": "current_field"}]
    assert session.latest_enum_artifact == enum_slot
    assert session.latest_threat_artifact == threat_slot
    assert session.conversation_history == [{"role": "assistant", "content": "当前结果"}]
    assert len(captured) == 1
    assert "上传正确的excel，应包含原始日志一列" in captured[0]


def test不同Sheet分次上传后在当前主数据内累积(monkeypatch, tmp_path):
    """枚举附件以 Sheet 为身份键，上传新 Sheet 不得覆盖已有 Sheet。"""
    import web.file_handlers as file_handlers
    from contracts.planner_models import FillStep, StepStatus
    from application.session_projection import build_session_facts
    from application.adapters import EnumFillAdapter
    from application.execution import ExecutionContext
    from application.session_state import SessionState

    captured = []
    _mount_message_capture(monkeypatch, captured)
    monkeypatch.setattr(file_handlers, "read_element_content", lambda element: "")
    monkeypatch.setattr(file_handlers, "create_dataframe_elements", lambda rows: [])
    first_path = tmp_path / "first.xlsx"
    second_path = tmp_path / "second.xlsx"
    _write_enum_workbook(first_path, {"event_type3": [("EQUAL", "attack", "攻击")]})
    _write_enum_workbook(second_path, {"action": [("EQUAL", "allow", "允许")]})
    session = SessionState(
        decoded_data={
            "name": "current",
            "normalize": [
                {"index": "event_type3", "mappings": []},
                {"index": "action", "mappings": []},
            ],
        },
        decoded_fields=["event_type3", "action"],
    )

    asyncio.run(
        file_handlers.handle_file_upload(
            session,
            SimpleNamespace(name="first.xlsx", path=str(first_path)),
        )
    )
    first_step = FillStep(
        step_id="fill-first",
        type="fill",
        fill_kind="enum",
        target_fields=("event_type3",),
        source_ref="session.enum_mapping_table",
        config_ref="session.decoded_config",
    )
    first_result = asyncio.run(
        EnumFillAdapter().execute(
            first_step,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )
    assert first_result.status == StepStatus.SUCCESS
    asyncio.run(
        file_handlers.handle_file_upload(
            session,
            SimpleNamespace(name="second.xlsx", path=str(second_path)),
        )
    )

    assert set(session.enum_mapping_sheets) == {"event_type3", "action"}
    assert {row["目标字段"] for row in session.enum_preview} == {"event_type3", "action"}
    assert session.stale_enum_config_refs == {"session.decoded_config"}

    partial_result = asyncio.run(
        EnumFillAdapter().execute(
            first_step,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )
    assert partial_result.status == StepStatus.SUCCESS
    assert session.stale_enum_config_refs == {"session.decoded_config"}

    refill_step = FillStep(
        step_id="refill-all",
        type="fill",
        fill_kind="enum",
        target_fields=("event_type3", "action"),
        source_ref="session.enum_mapping_table",
        config_ref="session.decoded_config",
    )
    refill_result = asyncio.run(
        EnumFillAdapter().execute(
            refill_step,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )

    assert refill_result.status == StepStatus.SUCCESS
    mappings_by_field = {
        item["index"]: item["mappings"] for item in session.decoded_data["normalize"]
    }
    assert mappings_by_field == {
        "event_type3": [
            {"mappingType": "EQUAL", "orgValue": "attack", "mappingValue": "攻击"}
        ],
        "action": [
            {"mappingType": "EQUAL", "orgValue": "allow", "mappingValue": "允许"}
        ],
    }
    assert session.stale_enum_config_refs == set()
    assert session.enum_pending_refills == {}


def test同名Sheet重填完整替换旧贡献并保留其他来源(monkeypatch, tmp_path):
    """同名 Sheet 的修改、删除和新增生效，主数据原有 mappings 不受影响。"""
    import web.file_handlers as file_handlers
    from contracts.planner_models import ExportStep, FillStep, PlanDecision, StepStatus
    from application.session_projection import build_session_facts
    from application.adapters import EnumFillAdapter, ExportAdapter, create_default_adapters
    from application.execution import ExecutionContext, PlanExecutor
    from application.session_state import SessionState

    captured = []
    _mount_message_capture(monkeypatch, captured)
    monkeypatch.setattr(file_handlers, "read_element_content", lambda element: "")
    monkeypatch.setattr(file_handlers, "create_dataframe_elements", lambda rows: [])
    first_path = tmp_path / "enum-v1.xlsx"
    second_path = tmp_path / "enum-v2.xlsx"
    _write_enum_workbook(
        first_path,
        {
            "event_type3": [
                ("EQUAL", "attack", "攻击"),
                ("EQUAL", "obsolete", "旧规则"),
            ]
        },
    )
    _write_enum_workbook(
        second_path,
        {
            "event_type3": [
                ("EQUAL", "attack", "恶意活动"),
                ("EQUAL", "scan", "扫描"),
            ]
        },
    )
    base_mapping = {"mappingType": "EQUAL", "orgValue": "base", "mappingValue": "基础"}
    session = SessionState(
        decoded_data={
            "name": "current",
            "normalize": [
                {"index": "event_type3", "mappings": [base_mapping.copy()]},
            ],
        },
        decoded_fields=["event_type3"],
    )
    step = FillStep(
        step_id="enum-fill",
        type="fill",
        fill_kind="enum",
        target_fields=("event_type3",),
        source_ref="session.enum_mapping_table",
        config_ref="session.decoded_config",
    )

    asyncio.run(
        file_handlers.handle_file_upload(
            session,
            SimpleNamespace(name="enum-v1.xlsx", path=str(first_path)),
        )
    )
    first_result = asyncio.run(
        EnumFillAdapter().execute(
            step,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )
    assert first_result.status == StepStatus.SUCCESS

    asyncio.run(
        file_handlers.handle_file_upload(
            session,
            SimpleNamespace(name="enum-v2.xlsx", path=str(second_path)),
        )
    )
    assert session.stale_enum_config_refs == {"session.decoded_config"}
    blocked_export = asyncio.run(
        ExportAdapter().execute(
            ExportStep(
                step_id="export",
                type="export",
                source_ref="session.decoded_config",
            ),
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )
    assert blocked_export.status == StepStatus.NEEDS_INPUT
    assert blocked_export.error_code == "enum_refill_required"
    replacement_report = asyncio.run(
        PlanExecutor(create_default_adapters(team=None)).execute(
            PlanDecision(decision="execute", plan_id="replace-enum-sheet", steps=(step,)),
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
        )
    )

    assert replacement_report.status == StepStatus.SUCCESS
    assert replacement_report.results[0].changed_count == 3
    mappings = session.decoded_data["normalize"][0]["mappings"]
    assert mappings == [
        base_mapping,
        {"mappingType": "EQUAL", "orgValue": "attack", "mappingValue": "恶意活动"},
        {"mappingType": "EQUAL", "orgValue": "scan", "mappingValue": "扫描"},
    ]
    assert session.stale_enum_config_refs == set()
    assert session.enum_pending_refills == {}

    repeated_report = asyncio.run(
        PlanExecutor(create_default_adapters(team=None)).execute(
            PlanDecision(decision="execute", plan_id="repeat-enum-sheet", steps=(step,)),
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
        )
    )
    assert repeated_report.status == StepStatus.FAILED
    assert repeated_report.results[0].error_code == "no_effect"


def test多Sheet工作簿任一Sheet无有效规则时整份拒绝(monkeypatch, tmp_path):
    """多 Sheet 上传必须先完整校验，失败时原附件和输出有效性均不变。"""
    import web.file_handlers as file_handlers
    from application.session_state import SessionState

    captured = []
    _mount_message_capture(monkeypatch, captured)
    monkeypatch.setattr(file_handlers, "read_element_content", lambda element: "")
    workbook_path = tmp_path / "partially-invalid.xlsx"
    _write_enum_workbook(
        workbook_path,
        {
            "event_type3": [("EQUAL", "attack", "攻击")],
            "action": [],
        },
    )
    original_sheets = {
        "severity": [
            {
                "mappingType": "EQUAL",
                "orgValue": "high",
                "mappingValue": "高",
            }
        ]
    }
    original_preview = [
        {
            "目标字段": "severity",
            "mappingType": "EQUAL",
            "orgValue": "high",
            "mappingValue": "高",
        }
    ]
    session = SessionState(
        decoded_data={"name": "current"},
        enum_excel_path="original.xlsx",
        enum_preview=original_preview.copy(),
        enum_mapping_sheets=original_sheets.copy(),
        enum_fill_contributions={"session.decoded_config": {"severity": []}},
    )

    asyncio.run(
        file_handlers.handle_file_upload(
            session,
            SimpleNamespace(name="partially-invalid.xlsx", path=str(workbook_path)),
        )
    )

    assert session.enum_excel_path == "original.xlsx"
    assert session.enum_preview == original_preview
    assert session.enum_mapping_sheets == original_sheets
    assert session.enum_fill_contributions == {
        "session.decoded_config": {"severity": []}
    }
    assert session.stale_enum_config_refs == set()
    assert len(captured) == 1
    assert "没有有效规则" in captured[0]
