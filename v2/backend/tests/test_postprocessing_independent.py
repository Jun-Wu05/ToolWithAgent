"""Independent durable-boundary checks for #276, using real API/Store/Worker."""
from dataclasses import asdict
import json

import pytest

from application.execution_continuation import ExecutionContinuation
from application.recovery import RecoveryBudget
from contracts.planner_models import DeterministicPlan, EnumExtractStep, EnumValuesArtifact, StepResult, StepStatus, ThreatMappingStep
from contracts.session_artifacts import EnumArtifactSlot
from toolwithagent_v2.infrastructure.db import connect
from toolwithagent_v2.infrastructure.store import Store
from toolwithagent_v2.runtime.postprocessing import freeze_session, state_digest
from toolwithagent_v2.runtime.worker import Worker
from toolwithagent_v2.settings import Settings

from test_postprocessing import Planner, current, excel, operation, rules, setup, upload


@pytest.mark.parametrize("exhausted", [False, True])
def test_durable_completed_ledger_and_recovery_budget_survive_confirmation_restart(tmp_path, exhausted):
    planner = Planner()
    client, store, conversation, worker = setup(tmp_path, planner)
    upload(client, conversation, "logs.txt", "alarm=SQL注入\n".encode())
    assert worker.once()
    old_enum = None
    if not exhausted:
        operation(client, conversation, "enum_extract", target_field="alarm")
        assert worker.once()
        old_enum = current(store, conversation, "enum_values")
    message = client.post(f"/api/v2/conversations/{conversation}/messages", json={"content": "续跑"}).json()
    run = message["run"]["id"]
    claim = store.claim("worker")
    session, _ = store.read_business_session(claim)
    initial = freeze_session(session)
    enum = EnumValuesArtifact.model_validate(client.get(f"/api/v2/artifacts/{old_enum['id']}/content").json()) if old_enum else EnumValuesArtifact(item_count=1, values=("SQL注入",), field="alarm")
    enum_step = EnumExtractStep(step_id="enum", type="enum_extract", target_field="alarm")
    threat_step = ThreatMappingStep(step_id="threat", type="threat_mapping", source_ref="step:enum", depends_on=("enum",))
    pending_step = EnumExtractStep(step_id="pending", type="enum_extract", target_field="alarm")
    plan = DeterministicPlan(plan_id="frozen", steps=(enum_step, pending_step) if exhausted else (enum_step, threat_step))
    completed = StepResult(step_id="enum", operation_type="enum_extract", status=StepStatus.SUCCESS, artifact=enum)
    session.latest_enum_artifact = EnumArtifactSlot(artifact=enum, source_field="alarm")
    continuation = ExecutionContinuation(
        "execute_plan", ("enum",), asdict(RecoveryBudget(max_per_plan=1) if exhausted else RecoveryBudget()), state_digest(initial),
        frozen_plan=plan.model_dump(mode="json"),
        completed_results=(completed.model_dump(mode="json"),),
        staging_state=freeze_session(session), recovery_count=1 if exhausted else 2, step_recovery_counts={"enum": 1})
    token = store.wait_for_confirmation("worker", claim, continuation, kind="business_plan", payload={"operations": ["threat_mapping"]})
    assert token
    calls = []
    original_factory = worker.business_application.adapters_factory
    def adapters(team):
        result = original_factory(team)
        class EnumNeverRepeated:
            async def execute(self, step, context, dependencies):
                calls.append(step.step_id)
                raise TimeoutError("TRANSIENT")
        result["enum_extract"] = EnumNeverRepeated()
        return result
    worker.business_application.adapters_factory = adapters
    restarted = Store(Settings(data_dir=store.root))
    assert restarted.continuation(run).to_json() == continuation.to_json()
    response = client.post(f"/api/v2/runs/{run}/confirm", json={"token": token["token"], "checkpoint_revision": token["checkpoint_revision"]}, headers={"Idempotency-Key": "resume"})
    assert response.status_code == 200, response.text
    resumed = Worker(restarted, "worker", business_application=worker.business_application)
    assert resumed.once()
    assert planner.calls == 0
    assert restarted.get_run("dev-user", run)["status"] == ("failed" if exhausted else "succeeded")
    assert calls == (["pending"] if exhausted else [])
    assert restarted.continuation(run).recovery_count == (1 if exhausted else 2)
    assert restarted.continuation(run).step_recovery_counts == {"enum": 1}
    if not exhausted:
        published_enum = current(restarted, conversation, "enum_values")
        assert published_enum["id"] != old_enum["id"]
        assert published_enum["run_id"] == run
        facts = restarted.get_conversation("dev-user", conversation)["session_facts"]
        assert next(item for item in facts["referenceable_artifacts"] if item["artifact_type"] == "enum_values")["item_count"] == 1
        artifact = current(restarted, conversation, "threat_mapping")
        payload = client.get(f"/api/v2/artifacts/{artifact['id']}/content").json()
        assert payload["mappings"][0]["original_value"] == "SQL注入"


@pytest.mark.parametrize("invalidated", ["rotated", "expired", "cancelled"])
def test_invalid_confirmation_cannot_publish_and_keeps_old_success(tmp_path, invalidated):
    planner = Planner("proposal")
    client, store, conversation, worker = setup(tmp_path, planner)
    rules(client, conversation, worker)
    operation(client, conversation, "export", source_ref="session.decoded_config")
    assert worker.once()
    old = current(store, conversation, "config_export")
    run = client.post(f"/api/v2/conversations/{conversation}/messages", json={"content": "导出"}).json()["run"]["id"]
    assert worker.once()
    token = store.issue_resume_token("dev-user", run)
    if invalidated == "rotated":
        store.issue_resume_token("dev-user", run)
    elif invalidated == "expired":
        with connect(store.path) as db:
            db.execute("UPDATE confirmations SET expires_at='2000-01-01T00:00:00+00:00' WHERE run_id=?", (run,))
    else:
        store.cancel("dev-user", run, store.issue_cancel_token("dev-user", run)["token"])
    response = client.post(f"/api/v2/runs/{run}/confirm", json={"token": token["token"], "checkpoint_revision": token["checkpoint_revision"]})
    assert response.status_code == 409, response.text
    assert not worker.once()
    assert planner.calls == 1
    assert current(store, conversation, "config_export")["id"] == old["id"]
    assert not any(item["run_id"] == run for item in store.get_conversation("dev-user", conversation)["artifacts"])


def test_attachment_hash_change_blocks_confirmation_without_replacing_old_configuration(tmp_path):
    planner = Planner("proposal")
    client, store, conversation, worker = setup(tmp_path, planner)
    rules(client, conversation, worker)
    attachment = upload(client, conversation, "enum.xlsx", excel(), "enum_mapping")
    assert worker.once()
    operation(client, conversation, "fill", fill_kind="enum", target_fields=["事件结果"], source_ref="session.enum_mapping_table", config_ref="session.decoded_config")
    assert worker.once()
    old = current(store, conversation, "field_mapping")
    run = client.post(f"/api/v2/conversations/{conversation}/messages", json={"content": "导出"}).json()["run"]["id"]
    assert worker.once()
    token = store.issue_resume_token("dev-user", run)
    with connect(store.path) as db:
        reference = db.execute("SELECT storage_key FROM files WHERE id=?", (attachment["file"]["id"],)).fetchone()
    (store.root/reference["storage_key"]).write_bytes(excel("篡改值"))
    response = client.post(f"/api/v2/runs/{run}/confirm", json={"token": token["token"], "checkpoint_revision": token["checkpoint_revision"]})
    assert response.status_code == 409 and response.json()["error"]["code"] == "continuation_stale"
    assert current(store, conversation, "field_mapping")["id"] == old["id"]
    assert "篡改值" not in json.dumps(store.events("dev-user", conversation, 0), ensure_ascii=False)

def test_failure_after_successful_staging_step_keeps_prior_artifact_id(tmp_path, monkeypatch):
    from contracts.planner_models import PlanDecision
    from test_postprocessing import ThreatMember
    class MultiPlanner:
        async def plan(self, **kwargs):
            return PlanDecision.model_validate({"decision": "execute", "plan_id": "atomic", "steps": [
                {"step_id": "enum", "type": "enum_extract", "target_field": "alarm"},
                {"step_id": "threat", "type": "threat_mapping", "source_ref": "step:enum", "depends_on": ["enum"]}]})
    client, store, conversation, worker = setup(tmp_path, MultiPlanner())
    upload(client, conversation, "logs.txt", "alarm=SQL注入\n".encode())
    assert worker.once()
    operation(client, conversation, "enum_extract", target_field="alarm")
    assert worker.once()
    old = current(store, conversation, "enum_values")
    async def fail(self, *args, **kwargs):
        raise RuntimeError("PRIVATE-FAILURE")
        yield
    monkeypatch.setattr(ThreatMember, "arun", fail)
    run = client.post(f"/api/v2/conversations/{conversation}/messages", json={"content": "提取并映射"}).json()["run"]["id"]
    assert worker.once()
    assert store.get_run("dev-user", run)["status"] == "failed"
    assert current(store, conversation, "enum_values")["id"] == old["id"]
    assert not any(item["run_id"] == run for item in store.get_conversation("dev-user", conversation)["artifacts"])
    assert "PRIVATE-FAILURE" not in json.dumps(store.events("dev-user", conversation, 0))



def test_same_run_step_dependency_has_persisted_artifact_lineage(tmp_path):
    from contracts.planner_models import PlanDecision
    class DependencyPlanner:
        async def plan(self, **kwargs):
            return PlanDecision.model_validate({"decision": "execute", "plan_id": "lineage", "steps": [
                {"step_id": "enum", "type": "enum_extract", "target_field": "alarm"},
                {"step_id": "threat", "type": "threat_mapping", "source_ref": "step:enum", "depends_on": ["enum"]}]})
    client, store, conversation, worker = setup(tmp_path, DependencyPlanner())
    upload(client, conversation, "logs.txt", "alarm=SQL注入\n".encode())
    assert worker.once()
    run = client.post(f"/api/v2/conversations/{conversation}/messages", json={"content": "枚举然后映射"}).json()["run"]["id"]
    assert worker.once()
    assert store.get_run("dev-user", run)["status"] == "succeeded"
    enum = current(store, conversation, "enum_values")
    threat = current(store, conversation, "threat_mapping")
    assert enum["run_id"] == threat["run_id"] == run
    with connect(store.path) as db:
        edge = db.execute("SELECT 1 FROM artifact_edges WHERE source_artifact_id=? AND derived_artifact_id=?", (enum["id"], threat["id"])).fetchone()
    assert edge is not None, "step:enum must reference the newly published enum artifact, not only the frozen prior-run sources"
