import pytest

from fastapi.testclient import TestClient

from toolwithagent_v2.api.app import create_app
from toolwithagent_v2.infrastructure.store import Store
from toolwithagent_v2.runtime.worker import Worker
from toolwithagent_v2.settings import Settings


class FakeBusiness:
    def __init__(self):
        self.parse_status = "SUCCESS"
        self.submission_status = "created"

    async def parse(self, path, snapshot):
        if self.parse_status != "SUCCESS":
            return {"error": "log_parse_failed"}
        return {"classification": {
            "status": "SUCCESS",
            "classification_details": [{"logtype": "attack", "count": 3, "real_samples": "SECRET"}],
            "coverage": {"matched_lines": 3, "total_lines": 3},
        }, "submission_eligible": True, "submission_token": "token", "coverage": 1.0, "total_lines": 3}

    async def submit(self, path, snapshot, classification, connection=None):
        return {"submission_status": self.submission_status, "application_id": 42}


def setup(tmp_path):
    settings = Settings(data_dir=tmp_path / "data")
    client = TestClient(create_app(settings))
    store = client.app.state.store
    conversation = client.post("/api/v2/conversations", json={}).json()["id"]
    worker = Worker(store, "worker-a", business_application=FakeBusiness())
    return client, store, conversation, worker


def upload(client, conversation, worker):
    response = client.post(f"/api/v2/conversations/{conversation}/files",
                           files={"file": ("log.txt", b"kind=attack SECRET\n")})
    assert response.status_code == 201, response.text
    assert worker.once()
    return response.json()["file"]["id"]


def test_parse_publish_and_explicit_submission(tmp_path):
    client, store, conversation, worker = setup(tmp_path)
    file_id = upload(client, conversation, worker)
    queued = client.post(f"/api/v2/conversations/{conversation}/log-parse",
                         json={"file_id": file_id, "feature_field": "kind"})
    assert queued.status_code == 201, queued.text
    assert worker.once()
    detail = client.get(f"/api/v2/conversations/{conversation}").json()
    artifact = detail["artifacts"][0]
    assert artifact["kind"] == "log_classification"
    assert artifact["summary"]["coverage"] == {"matched_lines": 3, "total_lines": 3}
    assert "格式" in artifact["summary"]["rule_summary"]
    assert artifact["submission_eligible"]
    assert "SECRET" not in str(detail)
    assert client.post(f"/api/v2/artifacts/{artifact['id']}/submit-log-knowledge").status_code == 201
    assert worker.once()
    restarted = Store(Settings(data_dir=store.root))
    result = restarted.get_conversation("dev-user", conversation)["artifacts"][0]
    assert result["submission_status"] == "created"
    assert result["application_id"] == 42
    assert "SECRET" not in str(result)


def test_partial_failure_preserves_previous_artifact(tmp_path):
    client, store, conversation, worker = setup(tmp_path)
    file_id = upload(client, conversation, worker)
    url = f"/api/v2/conversations/{conversation}/log-parse"
    assert client.post(url, json={"file_id": file_id}).status_code == 201
    assert worker.once()
    first = client.get(f"/api/v2/conversations/{conversation}").json()["artifacts"][0]["id"]
    worker.business_application.parse_status = "PARTIAL"
    queued = client.post(url, json={"file_id": file_id}).json()
    assert worker.once()
    assert store.get_run("dev-user", queued["run"]["id"])["status"] == "failed"
    assert [a["id"] for a in store.get_conversation("dev-user", conversation)["artifacts"]] == [first]


def test_submission_stale_and_owner_guard(tmp_path):
    client, store, conversation, worker = setup(tmp_path)
    file_id = upload(client, conversation, worker)
    assert client.post(f"/api/v2/conversations/{conversation}/log-parse", json={"file_id": file_id}).status_code == 201
    assert worker.once()
    artifact_id = store.get_conversation("dev-user", conversation)["artifacts"][0]["id"]
    replacement = client.post(f"/api/v2/conversations/{conversation}/files",
                              files={"file": ("replacement.txt", b"kind=replacement\n")})
    assert replacement.status_code == 201, replacement.text
    assert client.post(f"/api/v2/artifacts/{artifact_id}/submit-log-knowledge").status_code == 201
    assert worker.once()  # 先校验排队的新主数据，再执行旧分类的申请。
    assert worker.once()
    detail = store.get_conversation("dev-user", conversation)
    assert detail["artifacts"][0]["submission_status"] == "stale"
    assert client.post(f"/api/v2/artifacts/{artifact_id}/submit-log-knowledge").status_code == 400
    client.post("/api/v2/dev/session", json={"user_id": "dev-other"})
    assert client.post(f"/api/v2/artifacts/{artifact_id}/submit-log-knowledge").status_code == 403


def test_json_array_is_split_into_log_records(tmp_path):
    from toolwithagent_v2.runtime.business_application import raw_log_lines
    path = tmp_path / "logs.json"
    path.write_text('[{"kind":"a"},{"kind":"b"}]', encoding="utf-8")
    assert raw_log_lines(path, "application/json") == ['{"kind": "a"}', '{"kind": "b"}']


def test_excel_understated_dimension_still_reads_raw_log_column(tmp_path):
    from io import BytesIO
    import re
    from zipfile import ZipFile

    from openpyxl import Workbook
    from toolwithagent_v2.runtime.business_application import raw_log_lines

    workbook = Workbook()
    workbook.active.append(["类型", "原始日志"])
    workbook.active.append(["a", "kind=attack"])
    source = BytesIO()
    workbook.save(source)
    workbook.close()

    path = tmp_path / "logs.xlsx"
    with ZipFile(BytesIO(source.getvalue())) as original, ZipFile(path, "w") as broken:
        for member in original.infolist():
            content = original.read(member.filename)
            if member.filename == "xl/worksheets/sheet1.xml":
                content, replaced = re.subn(rb'<dimension\b[^>]*>', b'<dimension ref="A1"/>', content, count=1)
                assert replaced == 1
            broken.writestr(member, content)

    assert raw_log_lines(path, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet") == ["kind=attack"]


def test_excel_validation_checks_rows_beyond_understated_dimension(tmp_path):
    from io import BytesIO
    import re
    from zipfile import ZipFile

    from openpyxl import Workbook

    workbook = Workbook()
    workbook.active.append(["原始日志"])
    workbook.active.append([123])
    source = BytesIO()
    workbook.save(source)
    workbook.close()

    broken = BytesIO()
    with ZipFile(BytesIO(source.getvalue())) as original, ZipFile(broken, "w") as output:
        for member in original.infolist():
            content = original.read(member.filename)
            if member.filename == "xl/worksheets/sheet1.xml":
                content, replaced = re.subn(rb'<dimension\b[^>]*>', b'<dimension ref="A1"/>', content, count=1)
                assert replaced == 1
                assert b"<v>123</v>" in content
                content = content.replace(b"<v>123</v>", b"<v>not-a-number</v>")
            output.writestr(member, content)

    client, store, conversation, worker = setup(tmp_path)
    response = client.post(f"/api/v2/conversations/{conversation}/files",
                           files={"file": ("bad.xlsx", broken.getvalue())})
    assert response.status_code == 201
    assert worker.once()
    run = store.get_run("dev-user", response.json()["run"]["id"])
    assert run["status"] == "failed"
    assert run["error_code"] == "invalid_file_content"


def test_business_bridge_uses_application_log_parse_step(tmp_path, monkeypatch):
    import asyncio
    import json
    from application.adapters import log_parse
    from toolwithagent_v2.runtime.business_application import BusinessApplication

    monkeypatch.setattr(log_parse, "_identify_log_format", lambda _: '{"format":"kv","feature_field":"kind"}')
    monkeypatch.setattr(log_parse, "_classify_log_features", lambda *args, **kwargs: json.dumps({
        "status": "SUCCESS", "log_format": "kv", "log_format_detail": "KV",
        "feature_field": "kind", "coverage": {"total_lines": 3, "matched_lines": 3},
        "classification_details": [{"logtype": "attack", "count": 3}],
        "analysis": {"delimit": " ", "tab": "="},
    }))
    monkeypatch.setattr(log_parse, "_fill_log_samples", lambda classification, _: classification)
    source = tmp_path / "logs.txt"
    source.write_text("kind=attack src=1\nkind=attack src=2\nkind=attack src=3\n", encoding="utf-8")
    bridge = BusinessApplication(tmp_path / "v2-knowledge.sqlite3")
    result = asyncio.run(bridge.parse(source, {"media_type": "text/plain", "feature_field": "kind"}))
    assert result["classification"]["status"] == "SUCCESS"
    assert result["submission_eligible"]
    assert result["total_lines"] == 3
    assert (tmp_path / "v2-knowledge.sqlite3").exists()


def test_real_knowledge_submission_is_atomic_and_attributed(tmp_path, monkeypatch):
    import json
    from application.adapters import log_parse
    from toolwithagent_v2.infrastructure.db import connect

    monkeypatch.setattr(log_parse, "_identify_log_format", lambda _: '{"format":"kv","feature_field":"kind"}')
    monkeypatch.setattr(log_parse, "_classify_log_features", lambda *args, **kwargs: json.dumps({
        "status": "SUCCESS", "log_format": "kv", "log_format_detail": "KV",
        "feature_field": "kind", "coverage": {"total_lines": 3, "matched_lines": 3},
        "classification_details": [{"logtype": "attack", "count": 3}],
        "analysis": {"delimit": " ", "tab": "="},
    }))
    monkeypatch.setattr(log_parse, "_fill_log_samples", lambda classification, _: classification)
    client, store, conversation, _ = setup(tmp_path)
    worker = Worker(store, "worker-a")
    uploaded = client.post(f"/api/v2/conversations/{conversation}/files", files={
        "file": ("logs.txt", b"kind=attack src=1\nkind=attack src=2\nkind=attack src=3\n")}).json()
    assert worker.once()
    response = client.post(f"/api/v2/conversations/{conversation}/log-parse",
                           json={"file_id": uploaded["file"]["id"], "feature_field": "kind"})
    assert response.status_code == 201, response.text
    assert worker.once()
    artifact = store.get_conversation("dev-user", conversation)["artifacts"][0]
    assert artifact["submission_eligible"]
    response = client.post(f"/api/v2/artifacts/{artifact['id']}/submit-log-knowledge")
    assert response.status_code == 201, response.text
    assert worker.once()
    assert store.get_run("dev-user", response.json()["run"]["id"])["status"] == "succeeded"
    with connect(store.path) as db:
        rows = db.execute("SELECT id,submitter,status FROM log_knowledge_applications").fetchall()
        assert len(rows) == 1
        assert rows[0]["submitter"] == "dev-user"
        assert rows[0]["status"] == "pending"
    result = store.get_conversation("dev-user", conversation)["artifacts"][0]
    assert result["submission_status"] == "created"
    assert result["application_id"] == rows[0]["id"]


def test_cancelled_submission_cannot_enter_repository(tmp_path):
    client, store, conversation, worker = setup(tmp_path)
    file_id = upload(client, conversation, worker)
    client.post(f"/api/v2/conversations/{conversation}/log-parse", json={"file_id": file_id})
    assert worker.once()
    artifact_id = store.get_conversation("dev-user", conversation)["artifacts"][0]["id"]
    queued = client.post(f"/api/v2/artifacts/{artifact_id}/submit-log-knowledge").json()
    claim = store.claim("worker-a")
    token = client.post(f"/api/v2/runs/{queued['run']['id']}/cancel-token").json()["token"]
    assert client.post(f"/api/v2/runs/{queued['run']['id']}/cancel", json={"token": token}).status_code == 200
    assert not store.publish_submission("worker-a", claim, lambda _: (_ for _ in ()).throw(AssertionError("repository called")))
    assert store.get_conversation("dev-user", conversation)["artifacts"][0]["submission_status"] == "cancelled"


def test_submission_blob_failure_rolls_back_knowledge_write(tmp_path, monkeypatch):
    import os
    import pytest
    from toolwithagent_v2.infrastructure.db import connect

    client, store, conversation, worker = setup(tmp_path)
    file_id = upload(client, conversation, worker)
    client.post(f"/api/v2/conversations/{conversation}/log-parse", json={"file_id": file_id})
    assert worker.once()
    artifact_id = store.get_conversation("dev-user", conversation)["artifacts"][0]["id"]
    queued = client.post(f"/api/v2/artifacts/{artifact_id}/submit-log-knowledge").json()
    claim = store.claim("worker-a")
    assert claim

    def producer(db):
        db.execute("INSERT INTO audit_events(id,actor_id,action,target_type,target_id,created_at,reason) VALUES(?,?,?,?,?,?,?)",
                   ("rollback-probe", "dev-user", "test", "run", claim["id"], "2026-09-30T00:00:00Z", "probe"))
        return {"submission_status": "created", "application_id": 1}

    def fail_replace(source, target):
        raise OSError("simulated blob failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated blob failure"):
        store.publish_submission("worker-a", claim, producer)
    with connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM audit_events WHERE id='rollback-probe'").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM artifacts WHERE run_id=?", (queued["run"]["id"],)).fetchone()[0] == 0


def pending_replacement(client, store, conversation, worker, status):
    content = b"invalid json" if status == "failed" else b'{"kind":"replacement"}'
    response = client.post(f"/api/v2/conversations/{conversation}/files",
                           files={"file": ("replacement.json", content)})
    assert response.status_code == 201, response.text
    run_id = response.json()["run"]["id"]
    if status == "running":
        assert store.claim(worker.worker_id)["id"] == run_id
    elif status == "failed":
        assert worker.once()
    elif status == "cancelled":
        token = client.post(f"/api/v2/runs/{run_id}/cancel-token").json()["token"]
        assert client.post(f"/api/v2/runs/{run_id}/cancel", json={"token": token}).status_code == 200
    assert store.get_run("dev-user", run_id)["status"] == status


@pytest.mark.parametrize("status", ["queued", "running", "failed", "cancelled"])
def test_unsuccessful_replacement_preserves_submission_eligibility(tmp_path, status):
    client, store, conversation, worker = setup(tmp_path)
    file_id = upload(client, conversation, worker)
    assert client.post(f"/api/v2/conversations/{conversation}/log-parse",
                       json={"file_id": file_id}).status_code == 201
    assert worker.once()
    artifact_id = store.get_conversation("dev-user", conversation)["artifacts"][0]["id"]
    pending_replacement(client, store, conversation, worker, status)
    artifact = store.get_conversation("dev-user", conversation)["artifacts"][0]
    assert artifact["id"] == artifact_id
    assert artifact["submission_eligible"]
    response = client.post(f"/api/v2/artifacts/{artifact_id}/submit-log-knowledge")
    assert response.status_code == 201, response.text
    if status in ("failed", "cancelled"):
        assert worker.once()
        assert store.get_run("dev-user", response.json()["run"]["id"])["status"] == "succeeded"


@pytest.mark.parametrize("status", ["queued", "cancelled"])
def test_unsuccessful_replacement_preserves_claimed_submission(tmp_path, status):
    client, store, conversation, worker = setup(tmp_path)
    file_id = upload(client, conversation, worker)
    assert client.post(f"/api/v2/conversations/{conversation}/log-parse",
                       json={"file_id": file_id}).status_code == 201
    assert worker.once()
    artifact_id = store.get_conversation("dev-user", conversation)["artifacts"][0]["id"]
    response = client.post(f"/api/v2/artifacts/{artifact_id}/submit-log-knowledge")
    assert response.status_code == 201, response.text
    claim = store.claim(worker.worker_id)
    assert claim["id"] == response.json()["run"]["id"]
    pending_replacement(client, store, conversation, worker, status)
    calls = []

    def producer(db):
        calls.append("knowledge_write")
        return {"submission_status": "created", "application_id": 42}

    assert store.publish_submission(worker.worker_id, claim, producer)
    assert calls == ["knowledge_write"]
    assert store.get_run("dev-user", claim["id"])["status"] == "succeeded"
    artifact = store.get_conversation("dev-user", conversation)["artifacts"][0]
    assert artifact["submission_status"] == "created"
