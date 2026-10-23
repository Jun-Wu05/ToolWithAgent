import json

from fastapi.testclient import TestClient

from toolwithagent_v2.api.app import create_app
from toolwithagent_v2.settings import Settings


def setup(tmp_path):
    settings = Settings(data_dir=tmp_path / "data")
    app = create_app(settings)
    return TestClient(app), app.state.store


def as_admin(client):
    assert client.post("/api/v2/dev/session", json={"user_id": "dev-admin"}).status_code == 200


def test_admin_overview_and_cross_user_run_listing(tmp_path):
    client, _ = setup(tmp_path)
    conversation = client.post("/api/v2/conversations", json={"title": "用户会话"}).json()
    queued = client.post(f"/api/v2/conversations/{conversation['id']}/files", files={"file": ("a.csv", b"a,b\n1,2\n")}).json()
    with client:
        as_admin(client)
        overview = client.get("/api/v2/admin/overview").json()
        assert overview["runs"]["queued"] >= 1
        assert overview["users"] >= 3
        assert "worker" in overview
        runs = client.get("/api/v2/admin/runs").json()
        row = next(item for item in runs["items"] if item["id"] == queued["run"]["id"])
        assert row["status"] == "queued"
        assert row["owner_id"] == "dev-user"
        assert row["conversation_title"] == "用户会话"
        assert "input_snapshot_json" not in row and "lease_owner" not in row and "storage_key" not in row
        filtered = client.get("/api/v2/admin/runs?status=running").json()
        assert all(item["status"] == "running" for item in filtered["items"])


def test_admin_capabilities_are_role_fenced(tmp_path):
    client, _ = setup(tmp_path)
    with client:
        assert client.get("/api/v2/admin/overview").status_code == 403
        client.post("/api/v2/dev/session", json={"user_id": "dev-other"})
        for response in (
            client.get("/api/v2/admin/overview"),
            client.get("/api/v2/admin/runs"),
            client.get("/api/v2/admin/audit-events"),
        ):
            assert response.status_code == 403
            assert response.json()["error"]["code"] == "insufficient_capability"


def test_admin_cancels_queued_run_with_audit_trail(tmp_path):
    client, _ = setup(tmp_path)
    conversation = client.post("/api/v2/conversations", json={}).json()
    queued = client.post(f"/api/v2/conversations/{conversation['id']}/files", files={"file": ("a.csv", b"a,b\n1,2\n")}).json()
    with client:
        as_admin(client)
        cancelled = client.post(f"/api/v2/admin/runs/{queued['run']['id']}/cancel", json={"reason": "重复提交"}).json()
        assert cancelled == {"id": queued["run"]["id"], "status": "cancelled", "error_code": "cancelled_by_admin"}
        again = client.post(f"/api/v2/admin/runs/{queued['run']['id']}/cancel", json={})
        assert again.status_code == 409
        assert again.json()["error"]["code"] == "run_not_queued"
        audit = client.get("/api/v2/admin/audit-events").json()
        entry = next(item for item in audit["items"] if item["action"] == "cancel_queued")
        assert entry["actor_name"] == "管理员"
        assert entry["target_type"] == "run"
        assert entry["reason"] == "重复提交"
        assert entry["before"] == {"status": "queued"}
        assert entry["after"]["status"] == "cancelled"


def test_force_stop_records_sanitized_before_after(tmp_path):
    client, _ = setup(tmp_path)
    conversation = client.post("/api/v2/conversations", json={}).json()
    queued = client.post(f"/api/v2/conversations/{conversation['id']}/files", files={"file": ("a.csv", b"a,b\n1,2\n")}).json()
    with client:
        as_admin(client)
        stopped = client.post(f"/api/v2/admin/runs/{queued['run']['id']}/force-stop", json={"reason": "异常运行"}).json()
        assert stopped["error_code"] == "force_stopped"
        audit = client.get("/api/v2/admin/audit-events").json()
        entry = next(item for item in audit["items"] if item["action"] == "force_stop")
        assert entry["before"] == {"status": "queued"}
        assert entry["after"] == {"status": "cancelled", "error_code": "force_stopped"}
        serialized = json.dumps(audit, ensure_ascii=False)
        assert "storage_key" not in serialized and "input_snapshot" not in serialized and str(tmp_path) not in serialized
