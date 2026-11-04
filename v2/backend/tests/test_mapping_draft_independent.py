"""Independent API/SQLite/Worker regressions for persistent mapping Drafts."""
import base64
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from agent.tools.rule_generator import rules_to_base64_text
from toolwithagent_v2.api.app import create_app
from toolwithagent_v2.infrastructure.db import connect
from toolwithagent_v2.runtime.business_application import BusinessApplication
from toolwithagent_v2.runtime.mapping_drafts import operation_key
from toolwithagent_v2.runtime.worker import Worker
from toolwithagent_v2.settings import Settings


PRIVATE_SAMPLE = "private-independent-sample"
PRIVATE_WARNING = "private-independent-warning"


class IndependentBusiness:
    """Only the model-dependent initial mapping is replaced; apply is production."""

    apply_mapping_draft = BusinessApplication.apply_mapping_draft

    def __init__(self, readonly_link=False):
        self.readonly_link = readonly_link

    async def parse(self, path, snapshot):
        return {"classification": {"status": "SUCCESS", "classification_details": []},
                "total_lines": 1, "submission_eligible": False}

    async def field_mapping(self, path, snapshot, classification=None):
        config = [
            {"name": "same-name", "parser": {"filter": [{"fields": {"威胁类型": "%{description}"}}]},
             "normalize": [
                 {"index": "alpha", "field": "源地址", "result": [PRIVATE_SAMPLE],
                  "mappings": [{"orgValue": "old", "mappingValue": "old-target"}], "value": "old-default"},
                 {"index": "beta", "field": "目的地址"},
                 {"index": "gamma", "field": None},
                 {"index": "delta", "field": None},
                 {"index": "original_log", "field": "原始日志"},
                 {"index": "事件名称", "field": "事件名称", "value": "网络攻击"},
                 {"index": "description", "field": "威胁类型", "mappings": [{"orgValue": "attack", "mappingValue": "网络攻击"}]}]},
            {"name": "same-name", "normalize": [
                {"index": "alpha", "field": "源端口"},
                {"index": "beta", "field": "目的地址"},
                {"index": "gamma", "field": None},
                {"index": "nested.alpha", "field": "目的端口"}]},
            {"name": "third", "normalize": [
                {"index": "alpha", "field": None},
                {"index": "beta", "field": "目的端口"},
                {"index": "gamma", "field": None}]}]
        if self.readonly_link:
            config[1]["normalize"][0]["field"] = "威胁类型"
        sources = list(dict.fromkeys(entry["index"] for rule in config for entry in rule["normalize"]))
        return {
            "config": config,
            "mapping_rows": [{"原始字段名": source, "匹配状态": "解析异常" if source == "gamma" else "匹配成功"}
                             for source in sources],
            "samples": {"0": {"alpha": [{"value": PRIVATE_SAMPLE, "line_number": 1, "source": "raw-log"}]}},
            "event_annotations": [{"rule_name": "same-name", "status": "uncertain", "reason": PRIVATE_WARNING}],
            "warnings": [{"code": "threat_chain_warning", "message": PRIVATE_WARNING}],
            "download_kind": "mapped_sub_rules", "download_content": rules_to_base64_text(config),
        }


@pytest.fixture
def world(tmp_path, request):
    settings = Settings(data_dir=tmp_path / "data")
    client = TestClient(create_app(settings))
    store = client.app.state.store
    conversation_id = client.post("/api/v2/conversations", json={}).json()["id"]
    worker = Worker(store, "independent-worker", business_application=IndependentBusiness(**getattr(request, "param", {})))
    upload = client.post(f"/api/v2/conversations/{conversation_id}/files",
                         files={"file": ("independent.txt", f"type=x alpha={PRIVATE_SAMPLE}\n".encode())})
    assert upload.status_code == 201, upload.text
    file_id = upload.json()["file"]["id"]
    assert worker.once()
    # 分叉②（#435）：映射统一要求当前分类产物，脚手架先完成一次日志类型提取。
    parsed = client.post(f"/api/v2/conversations/{conversation_id}/log-parse", json={"file_id": file_id})
    assert parsed.status_code == 201, parsed.text
    assert worker.once()
    queued = client.post(f"/api/v2/conversations/{conversation_id}/field-mapping",
                         json={"file_id": file_id, "product": "private-product", "log_vendor": "private-vendor"},
                         headers={"Idempotency-Key": str(uuid4())})
    assert queued.status_code == 201, queued.text
    assert worker.once()
    artifact = next(item for item in store.get_conversation("dev-user", conversation_id)["artifacts"]
                    if item.get("current") and item["kind"] == "field_mapping")
    response = client.post(f"/api/v2/artifacts/{artifact['id']}/mapping-drafts")
    assert response.status_code == 200, response.text
    return SimpleNamespace(client=client, store=store, worker=worker, settings=settings,
                           conversation_id=conversation_id, file_id=file_id, artifact=artifact,
                           draft=response.json())


def edit(world, draft, source, target, rule="0", linked=(), client=None):
    client = client or world.client
    return client.patch(f"/api/v2/mapping-drafts/{draft['id']}/operations/{operation_key(rule, source)}",
                        json={"sub_rule_id": rule, "source_path": source, "standard_field": target,
                              "linked_sub_rule_ids": list(linked)},
                        headers={"If-Match": str(draft["revision"])})


def saved(response):
    assert response.status_code == 200, response.text
    return response.json()["draft"]


def draft_view(world, draft=None, rule="0"):
    response = world.client.get(f"/api/v2/artifacts/{world.artifact['id']}/mapping-view",
                                params={"sub_rule": rule, **({"draft_id": draft["id"]} if draft else {})})
    assert response.status_code == 200, response.text
    return {row["source_path"]: row for row in response.json()["items"]}


def read_draft(world, draft=None):
    response = world.client.get(f"/api/v2/mapping-drafts/{(draft or world.draft)['id']}")
    assert response.status_code == 200, response.text
    return response.json()


def confirm(world, draft, preview, *, key=None):
    assert preview.status_code == 409, preview.text
    details = preview.json()["error"]["details"]
    return world.client.post(f"/api/v2/mapping-drafts/{draft['id']}/replacement-confirmations",
                             json={"operation_key": details["operation_key"], "proposal": details["proposal"], "confirm": True},
                             headers={"If-Match": str(draft["revision"]), "Idempotency-Key": key or str(uuid4())})


def apply_draft(world, draft, *, key=None):
    return world.client.post(f"/api/v2/mapping-drafts/{draft['id']}/apply",
                             headers={"If-Match": str(draft["revision"]), "Idempotency-Key": key or str(uuid4())})


def send(world, text="continue"):
    return world.client.post(f"/api/v2/conversations/{world.conversation_id}/messages",
                             json={"content": text}, headers={"Idempotency-Key": str(uuid4())})


def test_independent_overlapping_scopes_remove_only_own_changes_and_fully_revert(world):
    draft = saved(edit(world, world.draft, "alpha", "事件描述", linked=("1", "2")))
    draft = saved(edit(world, draft, "alpha", "源地址", rule="1"))
    draft = saved(edit(world, draft, "alpha", "目的端口"))
    assert draft_view(world, draft)["alpha"]["standard_field"] == "目的端口"
    assert draft_view(world, draft, "1")["alpha"]["standard_field"] == "源地址"
    assert draft_view(world, draft, "2")["alpha"]["standard_field"] == ""
    assert draft["changed_count"] == 2
    draft = saved(edit(world, draft, "alpha", "源地址"))
    assert draft["changed_count"] == 1
    assert draft_view(world, draft, "1")["alpha"]["draft_modified"]
    draft = saved(edit(world, draft, "alpha", "源端口", rule="1"))
    assert draft["changed_count"] == 0
    assert not any(row["draft_modified"] for rule in ("0", "1", "2") for row in draft_view(world, draft, rule).values())
    assert send(world).status_code == 201
    assert apply_draft(world, draft).json()["error"]["code"] == "mapping_draft_empty"


def test_independent_replacement_overwrite_does_not_erase_later_occupant_edit(world):
    draft = saved(confirm(world, world.draft, edit(world, world.draft, "alpha", "目的地址")))
    draft = saved(edit(world, draft, "beta", "源端口"))
    draft = saved(edit(world, draft, "alpha", "事件描述"))
    rows = draft_view(world, draft)
    assert rows["alpha"]["standard_field"] == "事件描述"
    assert rows["beta"]["standard_field"] == "源端口"
    draft = saved(edit(world, draft, "alpha", "源地址"))
    assert draft["changed_count"] == 1
    draft = saved(edit(world, draft, "beta", "目的地址"))
    assert draft["changed_count"] == 0
    assert send(world).status_code == 201


def test_independent_two_connections_same_revision_have_one_winner_without_overwrite(world):
    clients = [TestClient(create_app(world.settings)), TestClient(create_app(world.settings))]
    gate = Barrier(2)

    def competing_save(position):
        gate.wait(timeout=10)
        return edit(world, world.draft, ("delta", "alpha")[position], ("事件描述", "源端口")[position],
                    client=clients[position])

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(competing_save, (0, 1)))
    assert sorted(response.status_code for response in responses) == [200, 409]
    loser = next(response for response in responses if response.status_code == 409)
    assert loser.json()["error"]["code"] == "draft_revision_conflict"
    draft = read_draft(world)
    assert draft["revision"] == world.draft["revision"] + 1
    assert draft["changed_count"] == 1 and draft["operation_count"] == 1
    chosen = next(index for index, response in enumerate(responses) if response.status_code == 200)
    rows = draft_view(world, draft)
    assert rows[("delta", "alpha")[chosen]]["draft_modified"]
    assert not rows[("alpha", "delta")[chosen]]["draft_modified"]


def test_independent_stale_confirmation_does_not_consume_newer_unrelated_edit(world):
    preview = edit(world, world.draft, "alpha", "目的地址")
    newer = saved(edit(world, world.draft, "delta", "事件描述"))
    rejected = confirm(world, world.draft, preview, key="stale-confirmation")
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "draft_revision_conflict"
    assert read_draft(world) == newer
    accepted = confirm(world, newer, preview, key="fresh-confirmation")
    draft = saved(accepted)
    rows = draft_view(world, draft)
    assert rows["alpha"]["standard_field"] == "目的地址" and rows["beta"]["standard_field"] == ""
    assert rows["delta"]["standard_field"] == "事件描述" and draft["changed_count"] == 3
    assert confirm(world, newer, preview, key="fresh-confirmation").json() == accepted.json()
    assert read_draft(world) == draft


@pytest.mark.parametrize("fault", ["staging_write", "rename", "artifact_insert", "outbox_insert"])
def test_independent_publication_fault_rolls_back_draft_artifact_and_outbox_then_retries(world, monkeypatch, fault):
    draft = saved(edit(world, world.draft, "alpha", "事件描述"))
    before = world.client.get(f"/api/v2/artifacts/{world.artifact['id']}/download").content
    receipt_key = "failure-then-retry"
    queued = apply_draft(world, draft, key=receipt_key)
    assert queued.status_code == 201, queued.text
    run_id = queued.json()["run"]["id"]
    with monkeypatch.context() as faults:
        if fault == "staging_write":
            original_open = Path.open

            def failing_open(path, mode="r", *args, **kwargs):
                if path.parent == world.store.root / "staging" and mode == "wb":
                    raise OSError("private-publish-fault-path")
                return original_open(path, mode, *args, **kwargs)

            faults.setattr(Path, "open", failing_open)
        elif fault == "rename":
            from toolwithagent_v2.infrastructure import store as store_module
            faults.setattr(store_module.os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("private-rename-fault")))
        else:
            with connect(world.store.path) as db:
                if fault == "artifact_insert":
                    db.execute("CREATE TRIGGER independent_publish_fault BEFORE INSERT ON artifacts WHEN NEW.run_id='" + run_id + "' BEGIN SELECT RAISE(ABORT,'independent-artifact-failure'); END")
                else:
                    db.execute("CREATE TRIGGER independent_publish_fault BEFORE INSERT ON conversation_events WHEN NEW.event_type='artifact_published' BEGIN SELECT RAISE(ABORT,'independent-outbox-failure'); END")
        assert world.worker.once()
    if fault in ("artifact_insert", "outbox_insert"):
        with connect(world.store.path) as db:
            db.execute("DROP TRIGGER independent_publish_fault")
    restored = read_draft(world)
    assert restored["status"] == "active"
    assert restored["revision"] == draft["revision"] and restored["operations"] == draft["operations"]
    assert restored["base_current"] and restored["changed_count"] == 1
    assert world.store.get_run("dev-user", run_id)["status"] == "failed"
    assert world.client.get(f"/api/v2/artifacts/{world.artifact['id']}/download").content == before
    with connect(world.store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM artifacts WHERE run_id=?", (run_id,)).fetchone()[0] == 0
        assert db.execute("SELECT status FROM artifacts WHERE id=?", (world.artifact["id"],)).fetchone()[0] == "published"
        assert db.execute("SELECT COUNT(*) FROM artifact_edges WHERE source_artifact_id=?", (world.artifact["id"],)).fetchone()[0] == 0
    assert not any(event["event_type"] == "artifact_published" and event["payload"].get("run_id") == run_id
                   for event in world.store.events("dev-user", world.conversation_id, 0))
    assert not list((world.store.root / "staging").iterdir())
    restarted = TestClient(create_app(world.settings))
    assert restarted.post(f"/api/v2/mapping-drafts/{draft['id']}/apply",
                          headers={"If-Match": str(draft["revision"]), "Idempotency-Key": receipt_key}).json() == queued.json()
    assert send(world).json()["error"]["code"] == "draft_resolution_required"
    retry = world.client.post(f"/api/v2/runs/{run_id}/retry", headers={"Idempotency-Key": "independent-retry"})
    assert retry.status_code == 201, retry.text
    assert world.worker.once()
    assert read_draft(world)["status"] == "applied"
    assert world.store.get_run("dev-user", retry.json()["id"])["status"] == "succeeded"
    assert send(world).status_code == 201


def test_independent_old_leader_cannot_publish_or_release_retried_apply(world):
    draft = saved(edit(world, world.draft, "alpha", "事件描述"))
    queued = apply_draft(world, draft).json()
    old_claim = world.store.claim(world.worker.worker_id)
    assert old_claim["id"] == queued["run"]["id"]
    with connect(world.store.path) as db:
        db.execute("UPDATE runs SET lease_expires_at='2000' WHERE id=?", (old_claim["id"],))
        db.execute("UPDATE worker_leases SET lease_expires_at='2000'")
    successor = Worker(world.store, "successor-worker", business_application=IndependentBusiness())
    assert world.store.claim(successor.worker_id) is None
    assert read_draft(world)["status"] == "active"
    retry = world.client.post(f"/api/v2/runs/{old_claim['id']}/retry", headers={"Idempotency-Key": "takeover-retry"})
    assert retry.status_code == 201, retry.text
    new_claim = world.store.claim(successor.worker_id)
    assert new_claim["id"] == retry.json()["id"]
    assert world.worker._run_mapping_draft_apply(old_claim) is False
    still_applying = read_draft(world)
    assert still_applying["status"] == "applying" and still_applying["apply_run_id"] == new_claim["id"]
    with connect(world.store.path) as db:
        assert not db.execute("SELECT 1 FROM artifacts WHERE run_id=?", (old_claim["id"],)).fetchone()
    assert successor._run_mapping_draft_apply(new_claim)
    assert read_draft(world)["status"] == "applied"
    assert send(world).status_code == 201


def test_independent_multiple_stale_drafts_are_discardable_after_database_restart(world):
    old = saved(edit(world, world.draft, "alpha", "事件描述"))
    queued = world.client.post(f"/api/v2/conversations/{world.conversation_id}/field-mapping",
                              json={"file_id": world.file_id, "product": "p", "log_vendor": "v"},
                              headers={"Idempotency-Key": "new-mapping"})
    assert queued.status_code == 201 and world.worker.once()
    new_artifact = next(item for item in world.store.get_conversation("dev-user", world.conversation_id)["artifacts"] if item.get("current") and item["kind"] == "field_mapping")
    newer = world.client.post(f"/api/v2/artifacts/{new_artifact['id']}/mapping-drafts").json()
    newer = saved(edit(world, newer, "delta", "源端口"))
    restarted = TestClient(create_app(world.settings))
    summaries = restarted.get(f"/api/v2/conversations/{world.conversation_id}").json()["drafts"]
    assert len(summaries) == 2 and next(item for item in summaries if item["id"] == old["id"])["base_current"] is False
    assert restarted.delete(f"/api/v2/mapping-drafts/{old['id']}", headers={"If-Match": str(old["revision"])}).status_code == 200
    assert send(world).status_code == 409
    assert restarted.delete(f"/api/v2/mapping-drafts/{newer['id']}", headers={"If-Match": str(newer["revision"])}).status_code == 200
    assert send(world).status_code == 201
    assert restarted.get(f"/api/v2/conversations/{world.conversation_id}").json()["drafts"] == []


def test_independent_fixed_targets_are_readonly_and_owner_privacy_survives_apply(world):
    rows = draft_view(world)
    for source in ("original_log", "事件名称", "description"):
        assert not rows[source]["editable"] and rows[source]["disabled_reason"] == "mapping_source_not_editable"
        rejected = edit(world, world.draft, source, None)
        assert rejected.status_code == 400 and rejected.json()["error"]["code"] == "mapping_source_not_editable"
    draft = saved(edit(world, world.draft, "alpha", "事件描述"))
    with connect(world.store.path) as db:
        db.execute("INSERT INTO users VALUES('independent-other','other','user',1,'now')")
    outsider = TestClient(create_app(world.settings))
    outsider.post("/api/v2/dev/session", json={"user_id": "independent-other"})
    assert outsider.get(f"/api/v2/mapping-drafts/{draft['id']}").status_code == 404
    assert outsider.get(f"/api/v2/artifacts/{world.artifact['id']}/mapping-view", params={"draft_id": draft["id"]}).status_code == 404
    assert outsider.get(f"/api/v2/artifacts/{world.artifact['id']}/download").status_code == 404
    assert edit(world, draft, "alpha", None, client=outsider).status_code == 404
    with connect(world.store.path) as db:
        db.execute("UPDATE users SET role='developer' WHERE id='dev-user'")
    assert edit(world, draft, "alpha", None).status_code == 403
    assert apply_draft(world, draft).status_code == 403
    assert world.client.delete(f"/api/v2/mapping-drafts/{draft['id']}", headers={"If-Match": str(draft["revision"])}).status_code == 403
    with connect(world.store.path) as db:
        db.execute("UPDATE users SET role='user' WHERE id='dev-user'")
    assert apply_draft(world, draft).status_code == 201 and world.worker.once()
    conversation = world.client.get(f"/api/v2/conversations/{world.conversation_id}").json()
    events = world.store.events("dev-user", world.conversation_id, 0)
    safe = json.dumps([conversation, events], ensure_ascii=False)
    assert all(secret not in safe for secret in (PRIVATE_SAMPLE, PRIVATE_WARNING, "nested.alpha"))
    # owner 亲填的表单参数只允许出现在自己的 operation 输入记录里，事件流与产物仍然禁止。
    assert all(secret not in json.dumps(events, ensure_ascii=False) for secret in ("private-product", "private-vendor"))
    assert all(secret not in json.dumps(m, ensure_ascii=False) for m in conversation["messages"] if m.get("kind") != "operation" for secret in ("private-product", "private-vendor"))
    assert any("private-product" in json.dumps(m, ensure_ascii=False) for m in conversation["messages"] if m.get("kind") == "operation")
    assert PRIVATE_SAMPLE in json.dumps(draft_view(world), ensure_ascii=False)


def test_independent_applied_download_view_metadata_and_lineage_agree(world):
    before_download = world.client.get(f"/api/v2/artifacts/{world.artifact['id']}/download").content
    before_config = json.loads(base64.b64decode(before_download))
    draft = saved(edit(world, world.draft, "delta", "事件描述"))
    response = apply_draft(world, draft)
    assert response.status_code == 201 and world.worker.once()
    new_artifact = next(item for item in world.store.get_conversation("dev-user", world.conversation_id)["artifacts"] if item.get("current") and item["kind"] == "field_mapping")
    all_rows = []
    for rule in ("0", "1", "2"):
        view = world.client.get(f"/api/v2/artifacts/{new_artifact['id']}/mapping-view", params={"sub_rule": rule}).json()
        all_rows.extend(view["items"])
        assert view["draft"] is None and view["warnings"][0]["message"] == PRIVATE_WARNING
        assert view["event_annotations"][0]["status"] == "uncertain"
        if rule == "0":
            assert view["items"][0]["source_path"] == "delta" and view["items"][0]["evidence"] == "用户选择"
    summary = new_artifact["summary"]
    assert summary["field_count"] == len(all_rows)
    assert summary["matched_count"] == sum(row["status"] == "matched" for row in all_rows)
    assert summary["unmatched_count"] == sum(row["status"] == "unmatched" for row in all_rows)
    assert summary["parse_error_count"] == sum(row["status"] == "parse_error" for row in all_rows)
    assert summary["uncertain_annotation_count"] == 1 and summary["warning_codes"] == ["threat_chain_warning"]
    downloaded = json.loads(base64.b64decode(world.client.get(f"/api/v2/artifacts/{new_artifact['id']}/download").content))
    delta = next(entry for entry in downloaded[0]["normalize"] if entry["index"] == "delta")
    assert delta["field"] == "事件描述" and delta["sim"] is True and delta["core"] is False
    for source in ("original_log", "事件名称", "description", "alpha"):
        assert next(entry for entry in downloaded[0]["normalize"] if entry["index"] == source) == next(entry for entry in before_config[0]["normalize"] if entry["index"] == source)
    assert downloaded[0]["parser"] == before_config[0]["parser"]
    assert world.client.get(f"/api/v2/artifacts/{world.artifact['id']}/download").content == before_download
    with connect(world.store.path) as db:
        assert db.execute("SELECT relation FROM artifact_edges WHERE source_artifact_id=? AND derived_artifact_id=?", (world.artifact["id"], new_artifact["id"])).fetchone()[0] == "mapping_edit"
        assert db.execute("SELECT version FROM artifacts WHERE id=?", (new_artifact["id"],)).fetchone()[0] == 2


@pytest.mark.parametrize("world", [{"readonly_link": True}], indirect=True)
def test_independent_same_source_readonly_candidate_is_disabled_before_linking(world):
    assert draft_view(world, rule="1")["alpha"]["editable"] is False
    response = edit(world, world.draft, "alpha", "事件描述")
    draft = saved(response)
    candidate = next(item for item in response.json()["candidates"]["items"] if item["sub_rule_id"] == "1")
    assert candidate["current_standard_field"] == "威胁类型"
    assert candidate["selectable"] is False
    assert candidate.get("disabled_reason") == "mapping_source_not_editable"
    assert read_draft(world) == draft
