import hashlib
import json
from fastapi.testclient import TestClient
from toolwithagent_v2.infrastructure.db import connect

from toolwithagent_v2.api.app import create_app
from toolwithagent_v2.settings import Settings


def test_task_and_run_history_is_owner_scoped_and_filterable(tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "data"))
    with TestClient(app) as client:
        first = client.post("/api/v2/conversations", json={"title": "甲会话"}).json()
        first_run = client.post(f"/api/v2/conversations/{first['id']}/messages", json={"content": "第一项"}).json()
        second = client.post("/api/v2/conversations", json={"title": "乙会话"}).json()
        second_run = client.post(f"/api/v2/conversations/{second['id']}/messages", json={"content": "第二项"}).json()

        tasks = client.get("/api/v2/tasks").json()
        runs = client.get("/api/v2/runs").json()
        assert tasks["total"] == runs["total"] == 2
        assert {item["conversation_id"] for item in tasks["items"]} == {first["id"], second["id"]}
        assert {item["conversation_id"] for item in runs["items"]} == {first["id"], second["id"]}
        assert {item["message_id"] for item in runs["items"]} == {first_run["id"], second_run["id"]}
        assert all("input_snapshot_json" not in item for item in tasks["items"] + runs["items"])
        assert client.get("/api/v2/runs?status=queued").json()["total"] == 2
        assert client.get("/api/v2/tasks?status=failed").json()["items"] == []
        assert client.get("/api/v2/runs?page=0").status_code == 422
        assert client.get("/api/v2/tasks?status=unknown").status_code == 422

        with connect(app.state.store.path) as db:
            db.execute("INSERT INTO users(id,display_name,role,is_active,created_at) VALUES(?,?,?,?,?)",
                       ("history-other", "另一用户", "user", 1, "2026-10-28T00:00:00Z"))
        assert client.post("/api/v2/dev/session", json={"user_id": "history-other"}).status_code == 200
        assert client.get("/api/v2/tasks").json()["items"] == []
        assert client.get("/api/v2/runs").json()["items"] == []
        other = client.post("/api/v2/conversations", json={"title": "私有"}).json()
        client.post(f"/api/v2/conversations/{other['id']}/messages", json={"content": "不可见"})
        assert client.post("/api/v2/dev/session", json={"user_id": "dev-user"}).status_code == 200
        assert client.get("/api/v2/tasks").json()["total"] == 2
        assert client.get("/api/v2/runs").json()["total"] == 2


def test_mapping_download_audits_once_and_denials_do_not_audit(tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "data"))
    with TestClient(app) as client:
        conversation = client.post("/api/v2/conversations", json={}).json()
        queued = client.post(f"/api/v2/conversations/{conversation['id']}/messages", json={"content": "映射"}).json()
        run = queued["run"]
        content = json.dumps({"download_kind": "mapped_sub_rules", "download_content": "safe"}).encode()
        digest = hashlib.sha256(content).hexdigest()
        key = f"artifacts/{digest[:2]}/{digest}"
        path = app.state.store.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        with connect(app.state.store.path) as db:
            task_id = db.execute("SELECT task_id FROM runs WHERE id=?", (run["id"],)).fetchone()[0]
            snapshot = json.loads(db.execute("SELECT input_snapshot_json FROM runs WHERE id=?", (run["id"],)).fetchone()[0])
            snapshot["file_id"] = "historical-file"
            db.execute("UPDATE runs SET input_snapshot_json=? WHERE id=?", (json.dumps(snapshot), run["id"]))
            db.execute("INSERT INTO artifacts(id,conversation_id,task_id,run_id,kind,version,status,storage_key,sha256,metadata_json,created_at,size) VALUES(?,?,?,?,?,1,'published',?,?,?,?,?)",
                       ("mapping-history", conversation["id"], task_id, run["id"], "field_mapping", key, digest, "{}", "2026-10-28T00:00:00Z", len(content)))
            db.execute("INSERT INTO artifacts(id,conversation_id,task_id,run_id,kind,version,status,metadata_json,created_at) VALUES(?,?,?,?,?,1,'published','{}',?)",
                       ("source-history", conversation["id"], task_id, run["id"], "source_fixture", "2026-10-28T00:00:00Z"))
            db.execute("INSERT INTO artifact_edges(source_artifact_id,derived_artifact_id,relation) VALUES(?,?,?)",
                       ("source-history", "mapping-history", "input"))
        artifact = next(item for item in client.get(f"/api/v2/conversations/{conversation['id']}").json()["artifacts"] if item["id"] == "mapping-history")
        assert artifact["version"] == 1 and artifact["source_artifact_ids"] == ["source-history"]
        assert artifact["status"] == "stale"
        response = client.get("/api/v2/artifacts/mapping-history/download")
        assert response.status_code == 200 and response.content == b"safe"
        with connect(app.state.store.path) as db:
            assert db.execute("SELECT COUNT(*) FROM audit_events WHERE action='artifact_download' AND target_id='mapping-history'").fetchone()[0] == 1
        assert client.post("/api/v2/dev/session", json={"user_id": "dev-other"}).status_code == 200
        assert client.get("/api/v2/artifacts/mapping-history/download").status_code == 404
        with connect(app.state.store.path) as db:
            assert db.execute("SELECT COUNT(*) FROM audit_events WHERE action='artifact_download' AND target_id='mapping-history'").fetchone()[0] == 1
        assert client.post("/api/v2/dev/session", json={"user_id": "dev-user"}).status_code == 200
        path.write_bytes(b"damaged")
        assert client.get("/api/v2/artifacts/mapping-history/download").status_code == 400
        with connect(app.state.store.path) as db:
            assert db.execute("SELECT COUNT(*) FROM audit_events WHERE action='artifact_download' AND target_id='mapping-history'").fetchone()[0] == 1
