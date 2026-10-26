import json

from fastapi.testclient import TestClient

from agent.tools.log_pattern_store import LogKnowledgeApplicationInput, LogKnowledgeRepository
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


def knowledge_input(submitter="dev-user", feature_field="log_type", recipe_version=1):
    return LogKnowledgeApplicationInput(
        recipe_version=recipe_version, structure_hash="hash-" + feature_field, structure_tokens=("time", "level", "msg"),
        format_type="json", format_spec={"format_detail": "json-lines"}, selection_mode="explicit",
        feature_field=feature_field, extractor_type="field_path", extractor_spec={"path": "$.log"},
        submitter=submitter, submission_note="冒烟申请")


def test_admin_log_knowledge_list_and_detail_bound_samples(tmp_path):
    client, store = setup(tmp_path)
    repository = LogKnowledgeRepository(store.path)
    application_id = repository.create_application(knowledge_input(), samples=[f"sample-line-{index}" for index in range(14)])
    with client:
        as_admin(client)
        listing = client.get("/api/v2/admin/log-knowledge").json()
        assert listing["total"] == 1 and listing["counts"]["pending"] == 1
        row = listing["items"][0]
        assert row["application_id"] == application_id and row["status"] == "pending"
        assert "samples" not in row and "extractor_spec" not in row
        detail = client.get(f"/api/v2/admin/log-knowledge/{application_id}").json()
        assert detail["status"] == "pending" and detail["format_type"] == "json"
        assert detail["sample_count"] == 10 and len(detail["samples"]) == 10
        assert detail["extractor_spec"] == {"path": "$.log"}
        missing = client.get("/api/v2/admin/log-knowledge/99999")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "log_knowledge_not_found"


def test_admin_log_knowledge_role_fenced(tmp_path):
    client, store = setup(tmp_path)
    with client:
        client.post("/api/v2/dev/session", json={"user_id": "dev-other"})
        for response in (
            client.get("/api/v2/admin/log-knowledge"),
            client.get("/api/v2/admin/log-knowledge/1"),
            client.post("/api/v2/admin/log-knowledge/1/approve", json={}),
            client.post("/api/v2/admin/log-knowledge/1/reject", json={"reason": "x"}),
            client.delete("/api/v2/admin/log-knowledge/1"),
        ):
            assert response.status_code == 403


def test_admin_approve_with_competing_replacement_requires_reason(tmp_path):
    client, store = setup(tmp_path)
    repository = LogKnowledgeRepository(store.path)
    first = repository.create_application(knowledge_input())
    second = repository.create_application(knowledge_input(recipe_version=2))
    with client:
        as_admin(client)
        approved = client.post(f"/api/v2/admin/log-knowledge/{first}/approve", json={}).json()
        assert approved == {"application_id": first, "status": "approved", "replaces_application_id": None}
        competing = client.post(f"/api/v2/admin/log-knowledge/{second}/approve", json={})
        assert competing.status_code == 409
        assert competing.json()["error"]["code"] == "log_knowledge_replacement_reason_required"
        replaced = client.post(f"/api/v2/admin/log-knowledge/{second}/approve", json={"reason": "新配方覆盖旧知识"}).json()
        assert replaced["replaces_application_id"] == first
        old = client.get(f"/api/v2/admin/log-knowledge/{first}").json()
        assert old["status"] == "rejected" and old["replaced_by_application_id"] == second
        audit = client.get("/api/v2/admin/audit-events").json()
        entry = next(item for item in audit["items"] if item["action"] == "log_knowledge_approve" and item["target_id"] == str(second))
        assert entry["reason"] == "新配方覆盖旧知识"
        assert entry["after"]["replaces_application_id"] == first


def test_admin_reject_and_delete_lifecycle(tmp_path):
    client, store = setup(tmp_path)
    repository = LogKnowledgeRepository(store.path)
    pending = repository.create_application(knowledge_input())
    rejected = repository.create_application(knowledge_input(feature_field="other"))
    with client:
        as_admin(client)
        no_reason = client.post(f"/api/v2/admin/log-knowledge/{pending}/reject", json={})
        assert no_reason.status_code == 400
        assert no_reason.json()["error"]["code"] == "log_knowledge_reason_required"
        declined = client.post(f"/api/v2/admin/log-knowledge/{pending}/reject", json={"reason": "样例不足"}).json()
        assert declined == {"application_id": pending, "status": "rejected"}
        reapprove = client.post(f"/api/v2/admin/log-knowledge/{pending}/approve", json={})
        assert reapprove.status_code == 409
        assert reapprove.json()["error"]["code"] == "log_knowledge_not_pending"
        delete_pending = client.delete(f"/api/v2/admin/log-knowledge/{rejected}")
        assert delete_pending.status_code == 409
        assert delete_pending.json()["error"]["code"] == "log_knowledge_not_rejected"
        removed = client.delete(f"/api/v2/admin/log-knowledge/{pending}").json()
        assert removed == {"application_id": pending, "status": "deleted"}
        assert client.get(f"/api/v2/admin/log-knowledge/{pending}").status_code == 404
        audit = client.get("/api/v2/admin/audit-events").json()
        actions = [item["action"] for item in audit["items"]]
        assert actions.count("log_knowledge_reject") == 1 and actions.count("log_knowledge_delete") == 1
