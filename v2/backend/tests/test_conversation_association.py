"""会话关联契约：输入留痕、回复与 Run/产物的可回看关联。"""
import io

from fastapi.testclient import TestClient

from toolwithagent_v2.api.app import create_app
from toolwithagent_v2.infrastructure.store import Store
from toolwithagent_v2.runtime.worker import Worker
from toolwithagent_v2.settings import Settings


def setup(tmp_path):
    settings = Settings(data_dir=tmp_path / "data")
    client = TestClient(create_app(settings))
    store = client.app.state.store
    conversation = client.post("/api/v2/conversations", json={}).json()
    return client, store, conversation["id"]


def upload_log(client, conversation_id, name="demo.log", content="level=info message=hello\n", key=None):
    headers = {"Idempotency-Key": key} if key else None
    response = client.post(
        f"/api/v2/conversations/{conversation_id}/files",
        files={"file": (name, io.BytesIO(content.encode("utf-8")), "text/plain")},
        data={"role": "primary"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def detail(client, conversation_id):
    return client.get(f"/api/v2/conversations/{conversation_id}").json()


def file_messages(payload):
    return [m for m in payload["messages"] if m["kind"] == "file"]


def operation_messages(payload):
    return [m for m in payload["messages"] if m["kind"] == "operation"]


def run_by_id(payload, run_id):
    return next(r for r in payload["runs"] if r["id"] == run_id)


def test_upload_creates_replayable_input_message(tmp_path):
    client, store, conversation_id = setup(tmp_path)
    result = upload_log(client, conversation_id, key="upload-1")
    payload = detail(client, conversation_id)
    records = file_messages(payload)
    assert len(records) == 1
    record = records[0]
    assert record["actor"] == "user"
    assert result["file"]["name"] in record["content"]
    assert record["payload"]["action"] == "file_upload"
    assert record["payload"]["file_id"] == result["file"]["id"]
    assert record["payload"]["name"] == result["file"]["name"]
    assert record["payload"]["size"] == result["file"]["size"]
    assert record["payload"]["role"] == "primary"
    ingest = run_by_id(payload, result["run"]["id"])
    assert ingest["kind"] == "file_ingest"
    assert ingest["message_id"] == record["id"]
    replay = upload_log(client, conversation_id, key="upload-1")
    assert replay["file"]["id"] == result["file"]["id"]
    assert len(file_messages(detail(client, conversation_id))) == 1


def test_log_parse_submission_records_params_and_run_link(tmp_path):
    client, store, conversation_id = setup(tmp_path)
    uploaded = upload_log(client, conversation_id)
    assert Worker(store, "worker-a").once()
    response = client.post(
        f"/api/v2/conversations/{conversation_id}/log-parse",
        json={"file_id": uploaded["file"]["id"], "feature_field": "level"},
    )
    assert response.status_code == 201, response.text
    payload = detail(client, conversation_id)
    records = operation_messages(payload)
    assert len(records) == 1
    assert records[0]["payload"]["action"] == "log_parse"
    assert records[0]["payload"]["file_id"] == uploaded["file"]["id"]
    assert records[0]["payload"]["feature_field"] == "level"
    assert run_by_id(payload, response.json()["run"]["id"])["message_id"] == records[0]["id"]


def test_field_mapping_message_records_source_params(tmp_path):
    client, store, conversation_id = setup(tmp_path)
    uploaded = upload_log(client, conversation_id)
    assert Worker(store, "worker-a").once()
    body = {"file_id": uploaded["file"]["id"], "product": "防火墙", "log_vendor": "华为", "data_source": "日志"}
    response = client.post(
        f"/api/v2/conversations/{conversation_id}/field-mapping",
        json=body,
        headers={"Idempotency-Key": "mapping-1"},
    )
    assert response.status_code == 201, response.text
    payload = detail(client, conversation_id)
    records = operation_messages(payload)
    assert len(records) == 1
    assert records[0]["payload"]["action"] == "field_mapping"
    assert records[0]["payload"]["product"] == "防火墙"
    assert records[0]["payload"]["log_vendor"] == "华为"
    assert records[0]["payload"]["data_source"] == "日志"
    assert records[0]["payload"]["file_id"] == uploaded["file"]["id"]
    replay = client.post(
        f"/api/v2/conversations/{conversation_id}/field-mapping",
        json=body,
        headers={"Idempotency-Key": "mapping-1"},
    )
    assert replay.status_code == 201
    assert replay.json()["run"]["id"] == response.json()["run"]["id"]
    assert len(operation_messages(detail(client, conversation_id))) == 1


def test_operation_step_message_records_submission(tmp_path):
    client, store, conversation_id = setup(tmp_path)
    step = {"step_id": "operation", "type": "enum_extract", "target_field": "事件结果", "source_ref": "session.logs"}
    response = client.post(
        f"/api/v2/conversations/{conversation_id}/operations",
        json={"step": step},
    )
    assert response.status_code == 201, response.text
    payload = detail(client, conversation_id)
    records = operation_messages(payload)
    assert len(records) == 1
    assert records[0]["payload"]["action"] == "enum_extract"
    assert records[0]["payload"]["step"]["target_field"] == "事件结果"
    assert run_by_id(payload, response.json()["run"]["id"])["message_id"] == records[0]["id"]


def test_failed_reply_carries_run_id(tmp_path):
    client, store, conversation_id = setup(tmp_path)
    run_id = client.post(
        f"/api/v2/dev/conversations/{conversation_id}/fake-runs",
        json={"scenario": "fail", "session_facts": {}},
    ).json()["run"]["id"]
    claim = store.claim("worker-a")
    assert claim is not None and claim["id"] == run_id
    assert store.finish("worker-a", claim, "business_operation_failed", "操作失败，请检查输入后重试。")
    replies = [m for m in detail(client, conversation_id)["messages"] if m["actor"] == "assistant"]
    assert len(replies) == 1
    assert replies[0]["run_id"] == run_id
    assert "操作失败" in replies[0]["content"]


def test_retry_new_attempt_keeps_original_message_link(tmp_path):
    client, store, conversation_id = setup(tmp_path)
    sent = client.post(
        f"/api/v2/conversations/{conversation_id}/messages",
        json={"content": "请提取日志类型"},
    ).json()
    run_id = sent["run"]["id"]
    claim = store.claim("worker-a")
    assert claim is not None and claim["id"] == run_id
    assert store.finish("worker-a", claim, "business_operation_failed", "操作失败")
    retried = client.post(f"/api/v2/runs/{run_id}/retry")
    assert retried.status_code == 201, retried.text
    payload = detail(client, conversation_id)
    message_id = next(m["id"] for m in payload["messages"] if m["kind"] == "text")
    original = run_by_id(payload, run_id)
    attempt = run_by_id(payload, retried.json()["id"])
    assert attempt["attempt"] == 2
    assert original["message_id"] == attempt["message_id"] == message_id


def test_rename_conversation_updates_title_rejects_blank_and_outsiders(tmp_path):
    client, store, conversation_id = setup(tmp_path)
    response = client.patch(f"/api/v2/conversations/{conversation_id}", json={"title": "KvHead 验收"})
    assert response.status_code == 200, response.text
    assert response.json()["title"] == "KvHead 验收"
    assert client.get(f"/api/v2/conversations/{conversation_id}").json()["title"] == "KvHead 验收"
    assert client.patch(f"/api/v2/conversations/{conversation_id}", json={"title": "   "}).status_code == 400
    outsider = TestClient(create_app(Settings(data_dir=store.root)))
    outsider.cookies.set("v2_dev_user", "dev-other")
    assert outsider.patch(f"/api/v2/conversations/{conversation_id}", json={"title": "别人的"}).status_code == 404
    events = store.events("dev-user", conversation_id, 0)
    assert [e["event_type"] for e in events if e["event_type"] == "conversation_renamed"] == ["conversation_renamed"]
