"""Real failure producers and durable clear commands; production model calls forbidden."""
from collections import Counter

import httpx
import pytest

from agent.core.planner import PlannerService
from contracts.planner_models import PlanDecision
from toolwithagent_v2.infrastructure.store import Store
from toolwithagent_v2.runtime.worker import Worker
from toolwithagent_v2.settings import Settings
from test_postprocessing import Planner, current, excel, operation, rules, setup, upload


@pytest.fixture(autouse=True)
def forbid_production_planner_and_model_http(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Production Planner/model HTTP is forbidden in offline tests")
    async def async_denied(*args, **kwargs):
        denied()
    monkeypatch.setattr(PlannerService, "plan", async_denied)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", denied)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", async_denied)


def test_real_execution_failure_produces_checkpoint_with_success_ledger_and_spent_budget(tmp_path):
    class ExecutePlanner:
        calls = 0
        async def plan(self, **kwargs):
            self.calls += 1
            return PlanDecision.model_validate({"decision": "execute", "plan_id": "failure-producer", "steps": [
                {"step_id": "prefix", "type": "enum_extract", "target_field": "alarm"},
                {"step_id": "pending", "type": "enum_extract", "target_field": "status"}]})
    planner = ExecutePlanner()
    client, store, conversation, worker = setup(tmp_path, planner)
    upload(client, conversation, "logs.txt", b"alarm=attack status=allow\n")
    assert worker.once()
    calls = Counter()
    original_factory = worker.business_application.adapters_factory
    def adapters(team):
        result = original_factory(team)
        original = result["enum_extract"]
        class Interruptible:
            async def execute(self, step, context, dependencies):
                calls[step.step_id] += 1
                if step.step_id == "pending" or calls["prefix"] == 1:
                    raise TimeoutError("offline transient failure")
                return await original.execute(step, context, dependencies)
        result["enum_extract"] = Interruptible()
        return result
    worker.business_application.adapters_factory = adapters
    run = client.post(f"/api/v2/conversations/{conversation}/messages", json={"content": "先提取alarm，再提取status"}).json()["run"]["id"]
    assert worker.once()
    assert calls == {"prefix": 2, "pending": 2}
    assert store.get_run("dev-user", run)["status"] == "waiting_confirmation"
    checkpoint = store.continuation(run)
    assert checkpoint is not None
    assert checkpoint.completed_step_refs == ("prefix",)
    assert checkpoint.recovery_count == 2
    assert checkpoint.step_recovery_counts == {"prefix": 1, "pending": 1}
    assert not store.get_conversation("dev-user", conversation)["artifacts"]
    token = client.post(f"/api/v2/runs/{run}/confirmation-token").json()
    response = client.post(f"/api/v2/runs/{run}/confirm", json={"token": token["token"], "checkpoint_revision": token["checkpoint_revision"]})
    assert response.status_code == 200, response.text
    restarted = Store(Settings(data_dir=store.root))
    assert Worker(restarted, "worker", business_application=worker.business_application).once()
    assert planner.calls == 1 and calls == {"prefix": 2, "pending": 3}
    assert restarted.continuation(run).recovery_count == 2
    assert restarted.get_run("dev-user", run)["status"] != "succeeded"


def test_explicit_clear_is_durable_and_blocks_old_worker_but_preserves_history(tmp_path):
    planner = Planner("proposal")
    client, store, conversation, worker = setup(tmp_path, planner)
    rules(client, conversation, worker)
    upload(client, conversation, "enum.xlsx", excel(), "enum_mapping")
    assert worker.once()
    operation(client, conversation, "fill", fill_kind="enum", target_fields=["事件结果"], source_ref="session.enum_mapping_table", config_ref="session.decoded_config")
    assert worker.once()
    old = current(store, conversation, "field_mapping")
    old_bytes = client.get(f"/api/v2/artifacts/{old['id']}/download").content
    late_run = operation(client, conversation, "export", source_ref="session.decoded_config")
    late_claim = store.claim("worker")
    assert late_claim["id"] == late_run
    clear = client.post(f"/api/v2/conversations/{conversation}/messages", json={"content": "清空数据"})
    assert clear.status_code == 201, clear.text
    assert worker.once()
    assert planner.calls == 0
    reopened = Store(Settings(data_dir=store.root))
    detail = reopened.get_conversation("dev-user", conversation)
    assert not any(file.get("mapping_eligible") for file in detail["files"])
    facts = detail["session_facts"]
    assert not facts["has_logs"] and not facts["has_decoded_config"]
    assert facts["available_config_refs"] == facts["enum_mapping_target_fields"] == facts["referenceable_artifacts"] == []
    assert not any(artifact.get("current") for artifact in detail["artifacts"])
    worker._run_business(late_claim)
    assert not any(artifact["run_id"] == late_run for artifact in reopened.get_conversation("dev-user", conversation)["artifacts"])
    assert client.get(f"/api/v2/artifacts/{old['id']}/content").status_code == 200
    assert client.get(f"/api/v2/artifacts/{old['id']}/download").content == old_bytes


def test_explicit_clear_invalidates_waiting_confirmation_without_planning(tmp_path):
    planner = Planner("proposal")
    client, store, conversation, worker = setup(tmp_path, planner)
    rules(client, conversation, worker)
    pending = client.post(f"/api/v2/conversations/{conversation}/messages", json={"content": "导出"}).json()["run"]["id"]
    assert worker.once()
    token = store.issue_resume_token("dev-user", pending)
    clear = client.post(f"/api/v2/conversations/{conversation}/messages", json={"content": "清空数据"})
    assert clear.status_code == 201, clear.text
    assert worker.once()
    assert planner.calls == 1
    response = client.post(f"/api/v2/runs/{pending}/confirm", json={"token": token["token"], "checkpoint_revision": token["checkpoint_revision"]})
    assert response.status_code == 409, response.text
    reopened = Store(Settings(data_dir=store.root))
    assert not reopened.get_conversation("dev-user", conversation)["session_facts"]["has_decoded_config"]

def test_explicit_clear_without_running_claim_remains_empty_after_restart(tmp_path):
    planner = Planner("proposal")
    client, store, conversation, worker = setup(tmp_path, planner)
    rules(client, conversation, worker)
    upload(client, conversation, "enum.xlsx", excel(), "enum_mapping")
    assert worker.once()
    operation(client, conversation, "fill", fill_kind="enum", target_fields=["事件结果"], source_ref="session.enum_mapping_table", config_ref="session.decoded_config")
    assert worker.once()
    old = current(store, conversation, "field_mapping")
    response = client.post(f"/api/v2/conversations/{conversation}/messages", json={"content": "清空数据"})
    assert response.status_code == 201, response.text
    assert worker.once()
    assert planner.calls == 0
    reopened = Store(Settings(data_dir=store.root))
    detail = reopened.get_conversation("dev-user", conversation)
    assert not detail["session_facts"]["has_decoded_config"]
    assert detail["session_facts"]["enum_mapping_target_fields"] == []
    assert detail["session_facts"]["referenceable_artifacts"] == []
    assert not any(file.get("mapping_eligible") for file in detail["files"])
    assert not any(artifact.get("current") for artifact in detail["artifacts"])
    assert client.get(f"/api/v2/artifacts/{old['id']}/download").status_code == 200
