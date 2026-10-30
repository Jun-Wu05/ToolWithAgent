"""Conversation summaries must not replay large business inputs."""
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from openpyxl.worksheet._read_only import ReadOnlyWorksheet

from toolwithagent_v2.api.app import create_app
from toolwithagent_v2.runtime.worker import Worker
from toolwithagent_v2.settings import Settings


def test_excel_details_read_only_presence_and_keep_full_business_input(tmp_path, monkeypatch):
    app = create_app(Settings(data_dir=tmp_path / "data"))
    client = TestClient(app)
    store = app.state.store
    conversation = client.post("/api/v2/conversations", json={}).json()["id"]
    workbook = Workbook()
    workbook.active.append(["类型", "原始日志"])
    workbook.active.append(["a", " "])
    for index in range(300):
        workbook.active.append(["a", f"kind=a value={index}"])
    stream = BytesIO()
    workbook.save(stream)
    workbook.close()
    response = client.post(f"/api/v2/conversations/{conversation}/files", files={"file": ("logs.xlsx", stream.getvalue())})
    assert response.status_code == 201
    assert Worker(store, "worker").once()
    rows_read = []
    original = ReadOnlyWorksheet.iter_rows

    def tracked(sheet, *args, **kwargs):
        for row in original(sheet, *args, **kwargs):
            rows_read.append(1)
            yield row

    def unnecessary_inference(*_args, **_kwargs):
        pytest.fail("page summary must not infer fields from logs")

    with monkeypatch.context() as patched:
        patched.setattr(ReadOnlyWorksheet, "iter_rows", tracked)
        patched.setattr("application.field_source.extract_log_fields_for_mapping", unnecessary_inference)
        for _ in range(2):
            detail = client.get(f"/api/v2/conversations/{conversation}").json()
            assert detail["session_facts_error"] is None
            assert detail["session_facts"]["has_logs"]
        assert len(rows_read) == 6  # Header, blank value, first real log on both requests.

    from toolwithagent_v2.infrastructure.db import connect
    with connect(store.path) as db:
        snapshot = store._freeze_business(db, conversation)
    session, _ = store.read_business_session({"owner_id": "dev-user", "conversation_id": conversation, "input": snapshot})
    assert len(session.raw_log_lines) == 300
    other = TestClient(app)
    other.cookies.set("v2_dev_user", "dev-other")
    assert other.get(f"/api/v2/conversations/{conversation}").status_code == 404
    (store.root / snapshot["storage_key"]).write_bytes(b"tampered")
    detail = client.get(f"/api/v2/conversations/{conversation}").json()
    assert detail["session_facts"] is None
    assert detail["session_facts_error"] == "business_input_unavailable"
    assert detail["messages"] and detail["files"]


def test_summary_projection_keeps_safe_facts_without_field_inference(monkeypatch):
    from application.session_projection import build_session_facts
    from toolwithagent_v2.runtime.postprocessing import BusinessSession, freeze_session, restore_session

    session = BusinessSession(raw_log_lines=["kind=a value=1", "kind=b value=2"], original_log=["kind=a value=1", "kind=b value=2"])
    expected = build_session_facts(session).model_dump(mode="json")
    state = freeze_session(session)
    summary = restore_session(state, log_limit=1)
    assert summary.raw_log_lines == session.raw_log_lines[:1]
    assert len(state["raw_log_lines"]) == 2
    monkeypatch.setattr("application.field_source.extract_log_fields_for_mapping", lambda *_args: pytest.fail("unexpected inference"))
    actual = build_session_facts(summary, include_field_pools=False).model_dump(mode="json")
    keys = ("has_logs", "has_log_classification", "has_decoded_config", "available_config_refs", "enum_mapping_target_fields", "enum_mapping_row_count", "mapped_sub_rule_count", "referenceable_artifacts")
    assert {key: actual[key] for key in keys} == {key: expected[key] for key in keys}


@pytest.mark.parametrize(("media", "content"), [
    ("text/csv", "原始日志\n \nfirst\nsecond\n"),
    ("application/x-ndjson", '\n {"value":1}\u2028{"value":2}\n'),
])
def test_limited_log_reads_skip_blank_records_and_preserve_full_reads(tmp_path, media, content):
    from toolwithagent_v2.runtime.business_application import raw_log_lines

    path = tmp_path / "logs"
    path.write_text(content, encoding="utf-8")
    full = raw_log_lines(path, media)
    assert len(full) == 2
    assert raw_log_lines(path, media, limit=1) == full[:1]
