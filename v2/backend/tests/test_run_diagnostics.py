"""Developer Run diagnostics are read-only and scoped by role and Run ID."""

import json
import time
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from toolwithagent_v2.api.app import create_app
from toolwithagent_v2.infrastructure.db import connect
from toolwithagent_v2.settings import Settings
from toolwithagent_v2.runtime.fake_application import FakeApplication
from toolwithagent_v2.runtime.worker import Worker
from contracts.model_call_diagnostics import record_call
from contracts.progress import PlannedStep, ProgressEvent, ProgressPhase, ProgressStatus
from toolwithagent_v2.runtime.progress import RunProgressSink
import asyncio


def setup(tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "data"))
    client = TestClient(app)
    conversation = client.post("/api/v2/conversations", json={"title": "诊断样本"}).json()
    queued = client.post(
        f"/api/v2/conversations/{conversation['id']}/files",
        files={"file": ("sample.csv", b"a,b\n1,2\n")},
    ).json()
    return client, app.state.store, queued["run"]["id"]


def switch(client, user_id):
    assert client.post("/api/v2/dev/session", json={"user_id": user_id}).status_code == 200


def test_developer_reads_cross_user_diagnostics_without_write_access(tmp_path):
    client, _, run_id = setup(tmp_path)
    assert client.get("/api/v2/developer/runs").status_code == 403
    assert client.get(f"/api/v2/developer/runs/{run_id}").status_code == 403
    assert client.get(f"/api/v2/developer/runs/{run_id}/bundle").status_code == 403
    assert client.get(f"/api/v2/developer/runs/{run_id}/calls/any").status_code == 403

    switch(client, "dev-other")
    assert client.get(f"/api/v2/runs/{run_id}").status_code == 404
    listed = client.get("/api/v2/developer/runs").json()
    assert run_id in [item["id"] for item in listed["items"]]
    detail = client.get(f"/api/v2/developer/runs/{run_id}").json()
    assert detail["run"]["id"] == run_id
    assert detail["run"]["owner_id"] == "dev-user"
    assert detail["calls"] == []
    assert detail["evidence_status"] == "未采集"
    assert client.post(f"/api/v2/runs/{run_id}/retry").status_code == 403
    assert client.post(f"/api/v2/runs/{run_id}/cancel-token").status_code == 403

    switch(client, "dev-admin")
    assert client.get(f"/api/v2/developer/runs/{run_id}").status_code == 200
    assert client.get("/api/v2/developer/runs/nonexistent").status_code == 404


def test_owner_reads_complete_paged_logs_and_model_content_without_cross_run_access(tmp_path):
    client, store, run_id = setup(tmp_path)
    claim = store.claim("worker-logs")
    assert claim["id"] == run_id
    for number in range(205):
        assert store.record_run_log("worker-logs", claim, {
            "created_at": 1793840400 + number, "level": "info", "logger": "pipeline",
            "step": "log_parse", "message": f"阶段 {number}: 日志原文 sample={number}", "exception": None,
        })
    prompt = "业务日志和 Prompt 原文 " + "甲" * 5000
    assert store.record_model_call("worker-logs", claim, {
        "provider": "deepseek", "model": "model-a", "request": prompt + " api_key=secret-123",
        "response": "模型输出 " + "乙" * 5000 + " Authorization: Bearer secret-456",
    })
    detail = client.get(f"/api/v2/runs/{run_id}/diagnostics")
    assert detail.status_code == 200
    assert len(detail.json()["business_logs"]["items"]) == 100
    cursor = detail.json()["business_logs"]["next_cursor"]
    page = client.get(f"/api/v2/runs/{run_id}/logs?after={cursor}").json()
    assert len(page["items"]) == 100 and page["next_cursor"] is not None
    final = client.get(f"/api/v2/runs/{run_id}/logs?after={page['next_cursor']}").json()
    assert len(final["items"]) == 5 and final["next_cursor"] is None
    call_id = detail.json()["calls"][0]["id"]
    content = client.get(f"/api/v2/runs/{run_id}/calls/{call_id}").json()
    assert prompt in content["request"] and len(content["response"]) > 5000
    assert "secret-123" not in json.dumps(content) and "secret-456" not in json.dumps(content)
    switch(client, "dev-other")
    for suffix in ("diagnostics", "logs", f"calls/{call_id}", "bundle"):
        assert client.get(f"/api/v2/runs/{run_id}/{suffix}").status_code == 404
    assert client.get(f"/api/v2/developer/runs/{run_id}/logs").status_code == 200


def test_diagnostic_bundle_only_contains_linked_allowlisted_evidence(tmp_path):
    client, store, run_id = setup(tmp_path)
    other_id = setup_another_run(client)
    with connect(store.path) as db:
        db.execute(
            "INSERT INTO model_calls(id,run_id,provider,model,error_code,summary_json,created_at) VALUES(?,?,?,?,?,?,?)",
            ("call-1", run_id, "deepseek", "model-a", "model_timeout",
             json.dumps({"request_id": "request-1", "scope_id": "step-1", "attempt": 2,
                         "duration_ms": 30000, "status": "failed", "request": "safe input",
                         "Authorization": "Bearer super-secret", "cookie": "session-secret",
                         "response": "api_key=super-secret"}), "2026-10-27T00:00:00Z"),
        )
        db.execute(
            "INSERT INTO model_calls(id,run_id,provider,model,error_code,summary_json,created_at) VALUES(?,?,?,?,?,?,?)",
            ("other-call", other_id, "deepseek", "model-b", None,
             json.dumps({"request_id": "other-request", "request": "private other user"}),
             "2026-10-27T00:00:01Z"),
        )
    switch(client, "dev-other")
    response = client.get(f"/api/v2/developer/runs/{run_id}/bundle")
    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment;")
    bundle = response.json()
    assert [item["id"] for item in bundle["calls"]] == ["call-1"]
    assert bundle["calls"][0]["request_id"] == "request-1"
    assert bundle["calls"][0]["error_code"] == "model_timeout"
    serialized = json.dumps(bundle, ensure_ascii=False)
    for secret in ("super-secret", "session-secret", "private other user", "Authorization", "cookie"):
        assert secret not in serialized
    assert bundle["run"]["id"] == run_id
    overview = client.get(f"/api/v2/developer/runs/{run_id}").json()
    assert "request" not in overview["calls"][0]
    assert "response" not in overview["calls"][0]
    call = client.get(f"/api/v2/developer/runs/{run_id}/calls/call-1")
    assert call.status_code == 200
    assert call.json()["request"] == "safe input"
    assert "super-secret" not in json.dumps(call.json())
    assert client.get(f"/api/v2/developer/runs/{run_id}/calls/other-call").status_code == 404


def setup_another_run(client):
    conversation = client.post("/api/v2/conversations", json={}).json()
    queued = client.post(
        f"/api/v2/conversations/{conversation['id']}/files",
        files={"file": ("other.csv", b"a,b\n3,4\n")},
    ).json()
    return queued["run"]["id"]


def test_model_call_evidence_obeys_worker_fence_and_survives_restart(tmp_path):
    client, store, run_id = setup(tmp_path)
    claim = store.claim("worker-270")
    assert claim["id"] == run_id
    event = {"request_id": "local-request", "scope_id": "step-1", "attempt": 1,
             "provider": "deepseek", "model": "model-a", "status": "failed",
             "error_code": "model_timeout", "duration_ms": 1200,
             "request": "Authorization: Bearer secret-270", "response": None,
             "skill_id": "skills/regex-extract-field",
             "tool_id": "agent.tools.pipeline.llm_client._call_llm_direct"}
    assert store.record_model_call("worker-270", claim, event)
    assert store.finish("worker-270", claim, "field_mapping_failed")
    assert not store.record_model_call("worker-270", claim, event)
    switch(client, "dev-other")
    detail = client.get(f"/api/v2/developer/runs/{run_id}").json()
    assert len(detail["calls"]) == 1
    assert detail["calls"][0]["error_code"] == "model_timeout"
    assert detail["calls"][0]["request_id"] == "local-request"
    assert detail["calls"][0]["skill_id"] == "skills/regex-extract-field"
    assert detail["calls"][0]["tool_id"] == "agent.tools.pipeline.llm_client._call_llm_direct"
    assert "secret-270" not in json.dumps(detail)
    restarted = TestClient(create_app(Settings(data_dir=store.root)))
    switch(restarted, "dev-other")
    assert restarted.get(f"/api/v2/developer/runs/{run_id}").json()["calls"] == detail["calls"]


def test_recovered_model_error_is_not_presented_as_run_root_cause(tmp_path):
    client, store, run_id = setup(tmp_path)
    claim = store.claim("worker-270")
    assert claim["id"] == run_id
    for index, error_code in enumerate(("model_timeout", None), 1):
        assert store.record_model_call("worker-270", claim, {
            "request_id": f"request-{index}", "provider": "deepseek", "model": "model-a",
            "status": "failed" if error_code else "succeeded", "error_code": error_code,
        })
    assert store.finish("worker-270", claim, "field_mapping_failed")
    switch(client, "dev-other")
    conclusion = client.get(f"/api/v2/developer/runs/{run_id}").json()["conclusion"]
    assert conclusion["category"] == "field_mapping_failed"
    assert conclusion["call_id"] is None
    assert conclusion.get("possible_cause") is None


def test_same_error_code_after_recovery_is_still_only_historical_evidence(tmp_path):
    client, store, run_id = setup(tmp_path)
    claim = store.claim("worker-270")
    for index, error_code in enumerate(("model_timeout", None), 1):
        assert store.record_model_call("worker-270", claim, {
            "request_id": f"request-{index}", "provider": "deepseek", "model": "model-a",
            "error_code": error_code,
        })
    assert store.finish("worker-270", claim, "model_timeout")
    switch(client, "dev-other")
    conclusion = client.get(f"/api/v2/developer/runs/{run_id}").json()["conclusion"]
    assert conclusion["call_id"] is None
    assert conclusion["evidence_call_id"] is not None
    assert conclusion["possible_cause"] is None


def test_plan_outline_projects_only_real_unexecuted_nodes(tmp_path):
    client, store, run_id = setup(tmp_path)
    claim = store.claim("worker-270")
    sink = RunProgressSink(store, "worker-270", claim)
    asyncio.run(sink.publish(ProgressEvent(
        plan_id="user-plan-secret", step_id="plan", phase=ProgressPhase.EXECUTION,
        status=ProgressStatus.RUNNING, message_code="plan_execution_started",
        planned_steps=(
            PlannedStep(step_id="first-secret", operation="log_parse"),
            PlannedStep(step_id="second-secret", operation="log_parse", depends_on=("first-secret",)),
        ),
    )))
    asyncio.run(sink.publish(ProgressEvent(
        plan_id="user-plan-secret", step_id="first-secret", phase=ProgressPhase.EXECUTION,
        status=ProgressStatus.FAILED, message_code="log_parse_failed",
    )))
    assert store.finish("worker-270", claim, "log_parse_failed")
    switch(client, "dev-other")
    detail = client.get(f"/api/v2/developer/runs/{run_id}").json()
    assert len(detail["planned_steps"]) == 2
    assert detail["unexecuted_steps"][0]["scope_id"] == detail["planned_steps"][1]["scope_id"]
    assert "Run 失败前未启动" in detail["unexecuted_steps"][0]["reason"]
    assert detail["planned_steps"][1]["dependency_scope_ids"] == [detail["planned_steps"][0]["scope_id"]]
    assert "secret" not in json.dumps(detail)


def test_worker_binds_model_calls_to_exact_run(tmp_path):
    client, store, _ = setup(tmp_path)
    conversation = client.post("/api/v2/conversations", json={}).json()
    queued = client.post(f"/api/v2/dev/conversations/{conversation['id']}/fake-runs", json={"scenario": "success"}).json()

    class RecordingApplication(FakeApplication):
        def execute(self, snapshot, continuation=None):
            record_call("deepseek", "model-a", "key-270", datetime.now(timezone.utc).isoformat(),
                        time.monotonic(), "api_key=key-270", response="done")
            return super().execute(snapshot, continuation)

    # The first queued file validation runs before the fake task.
    worker = Worker(store, application=RecordingApplication())
    assert worker.once()
    assert worker.once()
    switch(client, "dev-other")
    run_id = queued["run"]["id"]
    calls = client.get(f"/api/v2/developer/runs/{run_id}").json()["calls"]
    assert len(calls) == 1
    assert calls[0]["attempt"] == 1
    assert calls[0]["task_id"] == queued["task"]["id"]
    assert "key-270" not in json.dumps(calls)
