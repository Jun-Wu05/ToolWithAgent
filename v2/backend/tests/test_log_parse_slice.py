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
    assert client.post(f"/api/v2/artifacts/{artifact_id}/submit-log-knowledge").status_code == 201
    upload(client, conversation, worker)
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
