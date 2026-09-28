import hashlib
import json
import os
import time
import threading
from pathlib import Path

from fastapi.testclient import TestClient

from application.execution_continuation import ExecutionContinuation
from toolwithagent_v2.api.app import create_app
from toolwithagent_v2.infrastructure.db import connect
from toolwithagent_v2.infrastructure.store import Store
from toolwithagent_v2.runtime.fake_application import FakeApplication
from toolwithagent_v2.runtime.worker import Worker
from toolwithagent_v2.settings import Settings


def setup(tmp_path):
    settings = Settings(data_dir=tmp_path / "data")
    client = TestClient(create_app(settings))
    store = client.app.state.store
    conversation = client.post("/api/v2/conversations", json={}).json()
    return client, store, conversation["id"]


def fake(client, conversation_id, scenario="success", facts=None):
    response = client.post(
        f"/api/v2/dev/conversations/{conversation_id}/fake-runs",
        json={"scenario": scenario, "session_facts": facts or {}},
    )
    assert response.status_code == 201, response.text
    return response.json()["run"]["id"]


def test_continuation_contract_roundtrip():
    value = ExecutionContinuation("finish", ("step_one",), {"total": 2, "rederive": 1}, "abc")
    assert ExecutionContinuation.from_json(value.to_json()) == value


def test_confirm_resume_across_api_and_worker_restart(tmp_path):
    client, store, conversation_id = setup(tmp_path)
    run_id = fake(client, conversation_id, "confirm", {"version": 1})
    calls = {}
    assert Worker(store, "worker-a", application=FakeApplication(calls)).once()
    assert store.get_run("dev-user", run_id)["status"] == "waiting_confirmation"
    with connect(store.path) as db:
        checkpoint = db.execute("SELECT * FROM execution_checkpoints WHERE run_id=?", (run_id,)).fetchone()
        assert checkpoint["revision"] == 1
        assert db.execute("SELECT status FROM confirmations WHERE run_id=?", (run_id,)).fetchone()[0] == "pending"
    restarted = Store(Settings(data_dir=store.root))
    client2 = TestClient(create_app(Settings(data_dir=store.root)))
    token = client2.post(f"/api/v2/runs/{run_id}/confirmation-token").json()
    assert token["checkpoint_revision"] == 1
    assert client2.post(f"/api/v2/runs/{run_id}/confirm", json={
        "token": token["token"], "checkpoint_revision": 0,
    }).status_code == 409
    response = client2.post(f"/api/v2/runs/{run_id}/confirm", json={
        "token": token["token"], "checkpoint_revision": 1,
    })
    assert response.status_code == 200, response.text
    assert client2.post(f"/api/v2/runs/{run_id}/confirm", json={
        "token": token["token"], "checkpoint_revision": 1,
    }).status_code == 409
    assert Worker(restarted, "worker-a", application=FakeApplication(calls)).once()
    assert store.get_run("dev-user", run_id)["status"] == "succeeded"
    assert calls == {"planner": 1, "step_one": 1, "step_two": 1}
    with connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM artifacts WHERE run_id=? AND status='published'", (run_id,)).fetchone()[0] == 1
    events = store.events("dev-user", conversation_id, 0)
    assert [e["sequence"] for e in events] == list(range(1, len(events) + 1))
    assert store.events("dev-user", conversation_id, events[2]["sequence"]) == events[3:]


def test_stale_continuation_fails_without_artifact(tmp_path):
    client, store, conversation_id = setup(tmp_path)
    run_id = fake(client, conversation_id, "confirm", {"version": 1})
    assert Worker(store, "worker-a").once()
    token = store.issue_resume_token("dev-user", run_id)
    assert store.confirm("dev-user", run_id, token["token"], token["checkpoint_revision"])
    assert Worker(store, "worker-a", application=FakeApplication(facts={"version": 2})).once()
    assert store.get_run("dev-user", run_id)["error_code"] == "continuation_stale"
    with connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 0


def test_retry_snapshot_attempt_and_idempotency(tmp_path):
    client, store, conversation_id = setup(tmp_path)
    run_id = fake(client, conversation_id, "fail", {"v": 1})
    assert Worker(store, "worker-a").once()
    with connect(store.path) as db:
        db.execute("UPDATE runs SET provider_config_revision=7,prompt_version='p1',standard_field_version='s1' WHERE id=?", (run_id,))
        db.commit()
    response = client.post(f"/api/v2/runs/{run_id}/retry", headers={"Idempotency-Key": "again"})
    assert response.status_code == 201, response.text
    retried = response.json()
    assert retried["attempt"] == 2
    assert client.post(f"/api/v2/runs/{run_id}/retry", headers={"Idempotency-Key": "again"}).json() == retried
    with connect(store.path) as db:
        original = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        new = db.execute("SELECT * FROM runs WHERE id=?", (retried["id"],)).fetchone()
        assert (new["input_snapshot_json"], new["provider_config_revision"], new["prompt_version"], new["standard_field_version"]) == (
            original["input_snapshot_json"], 7, "p1", "s1"
        )
        assert db.execute("SELECT current_run_id FROM tasks WHERE id=?", (original["task_id"],)).fetchone()[0] == new["id"]
        assert db.execute("SELECT COUNT(*) FROM runs WHERE task_id=?", (original["task_id"],)).fetchone()[0] == 2


def test_cancel_and_admin_force_stop_fence_late_publication(tmp_path):
    client, store, conversation_id = setup(tmp_path)
    run_id = fake(client, conversation_id)
    claim = store.claim("worker-a")
    assert claim is not None
    token = client.post(f"/api/v2/runs/{run_id}/cancel-token").json()["token"]
    assert client.post(f"/api/v2/runs/{run_id}/cancel", json={"token": "wrong"}).status_code == 409
    assert client.post(f"/api/v2/runs/{run_id}/cancel", json={"token": token}).status_code == 200
    assert client.post(f"/api/v2/runs/{run_id}/cancel", json={"token": token}).status_code == 409
    assert not store.publish("worker-a", claim, b"late")
    assert not store.finish("worker-a", claim)
    queued = fake(client, conversation_id)
    client.post("/api/v2/dev/session", json={"user_id": "dev-admin"})
    response = client.post(f"/api/v2/admin/runs/{queued}/force-stop", json={"reason": "manual recovery"})
    assert response.status_code == 200, response.text
    with connect(store.path) as db:
        audit = db.execute("SELECT reason FROM audit_events WHERE target_id=?", (queued,)).fetchone()
        assert audit[0] == "manual recovery"
        assert db.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 0


def test_takeover_fences_future_run_lease_and_preserves_fifo(tmp_path):
    client, store, conversation_id = setup(tmp_path)
    first = fake(client, conversation_id)
    second = fake(client, conversation_id)
    claim = store.claim("worker-a", lease_seconds=60)
    assert claim["id"] == first
    assert store.claim("worker-a") is None
    with connect(store.path) as db:
        db.execute("UPDATE worker_leases SET lease_expires_at='2000-01-01T00:00:00+00:00'")
        db.commit()
    replacement = Store(Settings(data_dir=store.root))
    assert Worker(replacement, "worker-b").once()
    assert store.get_run("dev-user", first)["error_code"] == "worker_lost"
    assert store.get_run("dev-user", second)["status"] == "succeeded"
    assert not store.publish("worker-a", claim, b"late")
    continuation = ExecutionContinuation("finish", ("step_one",), {"total": 1}, "digest")
    assert store.wait_for_confirmation("worker-a", claim, continuation) is None
    with connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM artifacts WHERE run_id=?", (first,)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM execution_checkpoints WHERE run_id=?", (first,)).fetchone()[0] == 0
        assert db.execute("SELECT epoch FROM worker_leases").fetchone()[0] == 2


def test_blob_reconciliation_and_crash_points(tmp_path, monkeypatch):
    client, store, conversation_id = setup(tmp_path)
    run_id = fake(client, conversation_id)
    claim = store.claim("worker-a")
    from toolwithagent_v2.infrastructure import store as module
    real_replace = module.os.replace
    def fail_replace(src, dst):
        if str(src).endswith(".stage") and "artifacts" in str(dst):
            raise OSError("rename failure")
        return real_replace(src, dst)
    monkeypatch.setattr(module.os, "replace", fail_replace)
    try:
        store.publish("worker-a", claim, b"artifact")
        assert False, "expected rename failure"
    except OSError:
        pass
    monkeypatch.setattr(module.os, "replace", real_replace)
    assert list((store.root / "staging").glob("*.stage")) == []
    assert store.publish("worker-a", claim, b"artifact")
    with connect(store.path) as db:
        row = db.execute("SELECT storage_key FROM artifacts WHERE run_id=?", (run_id,)).fetchone()
    orphan = store.root / "artifacts" / "orphan"
    orphan.write_bytes(b"orphan")
    abandoned = store.root / "staging" / "abandoned.stage"
    abandoned.write_bytes(b"stage")
    active = store.root / "staging" / "active.stage"
    active.write_bytes(b"still being written")
    old = time.time() - 7200
    os.utime(orphan, (old, old))
    os.utime(abandoned, (old, old))
    published = store.root / row["storage_key"]
    published.write_bytes(b"corrupt")
    Store(Settings(data_dir=store.root))
    assert not orphan.exists()
    assert not abandoned.exists()
    assert active.exists()
    with connect(store.path) as db:
        assert db.execute("SELECT status FROM artifacts WHERE run_id=?", (run_id,)).fetchone()[0] == "corrupt"


def test_roles_and_old_run_confirmation(tmp_path):
    client, store, conversation_id = setup(tmp_path)
    run_id = fake(client, conversation_id, "confirm")
    assert Worker(store, "worker-a").once()
    token = store.issue_resume_token("dev-user", run_id)
    client.post("/api/v2/dev/session", json={"user_id": "dev-other"})
    for suffix in ("retry", "cancel-token", "confirmation-token"):
        assert client.post(f"/api/v2/runs/{run_id}/{suffix}").status_code == 403
    assert client.post(f"/api/v2/admin/runs/{run_id}/force-stop", json={"reason": "x"}).status_code == 403
    client.post("/api/v2/dev/session", json={"user_id": "dev-user"})
    cancel_token = store.issue_cancel_token("dev-user", run_id)
    assert store.cancel("dev-user", run_id, cancel_token["token"])
    assert client.post(f"/api/v2/runs/{run_id}/confirm", json={
        "token": token["token"], "checkpoint_revision": token["checkpoint_revision"],
    }).status_code == 409



def test_fake_runs_unavailable_in_production(tmp_path):
    client = TestClient(create_app(Settings(data_dir=tmp_path / "prod", development=False)))
    assert client.post("/api/v2/dev/conversations/any/fake-runs", json={}).status_code == 404
    assert client.post("/api/v2/conversations/any/fake-runs", json={}).status_code == 404


def test_cancel_queued_and_waiting_with_token_rotation(tmp_path):
    client, store, conversation_id = setup(tmp_path)
    queued = fake(client, conversation_id)
    first = client.post(f"/api/v2/runs/{queued}/cancel-token").json()["token"]
    second = client.post(f"/api/v2/runs/{queued}/cancel-token").json()["token"]
    assert client.post(f"/api/v2/runs/{queued}/cancel", json={"token": first}).status_code == 409
    assert client.post(f"/api/v2/runs/{queued}/cancel", json={"token": second}).status_code == 200
    assert store.get_run("dev-user", queued)["status"] == "cancelled"
    assert not Worker(store, "worker-a").once()
    waiting = fake(client, conversation_id, "confirm")
    assert Worker(store, "worker-a").once()
    assert store.get_run("dev-user", waiting)["status"] == "waiting_confirmation"
    token = client.post(f"/api/v2/runs/{waiting}/cancel-token").json()["token"]
    assert client.post(f"/api/v2/runs/{waiting}/cancel", json={"token": token}).status_code == 200
    assert store.get_run("dev-user", waiting)["status"] == "cancelled"
    events = [e["event_type"] for e in store.events("dev-user", conversation_id, 0)
              if e["resource_id"] == waiting]
    assert events[-2:] == ["run_cancelling", "run_cancelled"]
    with connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM artifacts WHERE run_id=?", (waiting,)).fetchone()[0] == 0


def test_admin_force_stops_running_run_and_records_audit(tmp_path):
    client, store, conversation_id = setup(tmp_path)
    run_id = fake(client, conversation_id)
    claim = store.claim("worker-a")
    client.post("/api/v2/dev/session", json={"user_id": "dev-admin"})
    assert client.post(f"/api/v2/admin/runs/{run_id}/force-stop", json={"reason": " "}).status_code == 400
    assert client.post(f"/api/v2/admin/runs/{run_id}/force-stop", json={"reason": "x" * 1001}).status_code == 400
    assert client.post(f"/api/v2/admin/runs/{run_id}/force-stop", json={"reason": "stuck worker"}).status_code == 200
    assert not store.publish("worker-a", claim, b"late")
    assert store.get_run("dev-user", run_id)["status"] == "cancelled"
    with connect(store.path) as db:
        assert db.execute("SELECT reason FROM audit_events WHERE target_id=?", (run_id,)).fetchone()[0] == "stuck worker"
        assert db.execute("SELECT COUNT(*) FROM artifacts WHERE run_id=?", (run_id,)).fetchone()[0] == 0


def test_rename_before_database_commit_leaves_only_reclaimable_orphan(tmp_path, monkeypatch):
    client, store, conversation_id = setup(tmp_path)
    run_id = fake(client, conversation_id)
    claim = store.claim("worker-a")
    original_record_state = store._record_state
    def crash_before_commit(db, row, status, error_code=None):
        raise RuntimeError("simulated crash after artifact insert, before commit")
    monkeypatch.setattr(store, "_record_state", crash_before_commit)
    try:
        store.publish("worker-a", claim, b"durable artifact")
        assert False, "expected crash"
    except RuntimeError:
        pass
    monkeypatch.setattr(store, "_record_state", original_record_state)
    with connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM artifacts WHERE run_id=?", (run_id,)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM conversation_events WHERE resource_type='artifact'").fetchone()[0] == 0
    final = store.root / "artifacts" / hashlib.sha256(b"durable artifact").hexdigest()[:2] / hashlib.sha256(b"durable artifact").hexdigest()
    assert final.exists()
    Store(Settings(data_dir=store.root))
    assert final.exists(), "recent orphan must survive startup while another worker may be publishing"
    old = time.time() - 7200
    os.utime(final, (old, old))
    Store(Settings(data_dir=store.root))
    assert not final.exists()


def test_simultaneous_workers_claim_only_one_run(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    client, store, conversation_id = setup(tmp_path)
    run_id = fake(client, conversation_id)
    gate = threading.Barrier(2)
    def attempt(worker_id):
        gate.wait(timeout=3)
        return store.claim(worker_id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        left = pool.submit(attempt, "worker-left")
        right = pool.submit(attempt, "worker-right")
        claims = [left.result(timeout=5), right.result(timeout=5)]
    assert [claim["id"] for claim in claims if claim] == [run_id]
    with connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM run_events WHERE run_id=? AND event_type='run_started'", (run_id,)).fetchone()[0] == 1


def test_expired_global_lease_reclaims_same_worker_id_with_new_epoch(tmp_path):
    client, store, conversation_id = setup(tmp_path)
    first = fake(client, conversation_id)
    second = fake(client, conversation_id)
    old_claim = store.claim("worker-id")
    assert old_claim["id"] == first
    with connect(store.path) as db:
        db.execute("UPDATE worker_leases SET lease_expires_at='2000-01-01T00:00:00+00:00'")
        db.commit()
    new_claim = store.claim("worker-id")
    assert new_claim["id"] == second
    assert new_claim["epoch"] > old_claim["epoch"]
    assert not store.finish("worker-id", old_claim)
    assert store.get_run("dev-user", first)["error_code"] == "worker_lost"


def test_expired_confirmation_cannot_resume(tmp_path):
    client, store, conversation_id = setup(tmp_path)
    run_id = fake(client, conversation_id, "confirm")
    assert Worker(store, "worker-a").once()
    token = store.issue_resume_token("dev-user", run_id)
    with connect(store.path) as db:
        db.execute("UPDATE confirmations SET expires_at='2000-01-01T00:00:00+00:00' WHERE run_id=? AND status='pending'", (run_id,))
        db.commit()
    assert client.post(f"/api/v2/runs/{run_id}/confirm", json={"token": token["token"], "checkpoint_revision": token["checkpoint_revision"]}).status_code == 409
    assert store.get_run("dev-user", run_id)["status"] == "waiting_confirmation"


def test_existing_v2_database_upgrades_without_losing_data(tmp_path):
    from alembic import command
    from alembic.config import Config
    root = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "data" / "v2.sqlite3"
    db_path.parent.mkdir()
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", "sqlite:///" + db_path.as_posix())
    command.upgrade(config, "0001_initial_runtime")
    with connect(db_path) as db:
        db.execute("INSERT INTO users(id,display_name,role,is_active,created_at) VALUES('existing','Existing','user',1,'2026-01-01')")
        db.execute("INSERT INTO conversations(id,owner_id,title,created_at,updated_at) VALUES('saved','existing','Saved','2026-01-01','2026-01-01')")
        db.commit()
    store = Store(Settings(data_dir=db_path.parent))
    assert store.get_conversation("existing", "saved")["title"] == "Saved"
    with connect(db_path) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0002_durable_runs"


def test_blob_reconciliation_serializes_with_publication(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    client, store, conversation_id = setup(tmp_path)
    run_id = fake(client, conversation_id)
    claim = store.claim("worker-a")
    content = b"old unreferenced content"
    digest = hashlib.sha256(content).hexdigest()
    final = store.root / "artifacts" / digest[:2] / digest
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_bytes(content)
    old = time.time() - 7200
    os.utime(final, (old, old))
    deleting = threading.Event()
    release = threading.Event()
    real_unlink = Path.unlink
    def pause_unlink(path, *args, **kwargs):
        if path == final:
            deleting.set()
            assert release.wait(timeout=5)
        return real_unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", pause_unlink)
    with ThreadPoolExecutor(max_workers=2) as pool:
        cleanup = pool.submit(store.reconcile_blobs)
        try:
            assert deleting.wait(timeout=3)
            publication = pool.submit(store.publish, "worker-a", claim, content)
            deadline = time.time() + 3
            while not list((store.root / "staging").glob("*.stage")) and time.time() < deadline:
                time.sleep(0.01)
            assert list((store.root / "staging").glob("*.stage"))
            assert not publication.done(), "publication must wait for reconciliation's write transaction"
        finally:
            release.set()
        cleanup.result(timeout=5)
        assert publication.result(timeout=5)
    assert final.read_bytes() == content
    with connect(store.path) as db:
        assert db.execute("SELECT status FROM artifacts WHERE run_id=?", (run_id,)).fetchone()[0] == "published"


def test_worker_renews_lease_during_slow_publication(tmp_path, monkeypatch):
    client, store, conversation_id = setup(tmp_path)
    run_id = fake(client, conversation_id)
    worker = Worker(store, "slow-publisher", lease_seconds=0.3)
    real_publish = store.publish
    entered = threading.Event()
    release = threading.Event()
    outcome = []
    def slow_publish(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=4)
        return real_publish(*args, **kwargs)
    monkeypatch.setattr(store, "publish", slow_publish)
    thread = threading.Thread(target=lambda: outcome.append(worker.once()))
    thread.start()
    try:
        assert entered.wait(timeout=3)
        time.sleep(0.65)
        assert store.claim("standby-worker") is None
    finally:
        release.set()
        thread.join(timeout=5)
    assert outcome == [True]
    assert store.get_run("dev-user", run_id)["status"] == "succeeded"


def test_slow_blob_integrity_scan_does_not_block_worker_renewal(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    client, store, conversation_id = setup(tmp_path)
    first = fake(client, conversation_id)
    assert Worker(store, "worker-a").once()
    with connect(store.path) as db:
        key = db.execute("SELECT storage_key FROM artifacts WHERE run_id=?", (first,)).fetchone()[0]
    target = store.root / key
    second = fake(client, conversation_id)
    claim = store.claim("worker-a", lease_seconds=1)
    assert claim["id"] == second
    reading = threading.Event()
    release = threading.Event()
    real_read_bytes = Path.read_bytes
    def slow_read_bytes(path):
        if path == target:
            reading.set()
            assert release.wait(timeout=5)
        return real_read_bytes(path)
    monkeypatch.setattr(Path, "read_bytes", slow_read_bytes)
    with ThreadPoolExecutor(max_workers=2) as pool:
        scan = pool.submit(store.reconcile_blobs)
        try:
            assert reading.wait(timeout=3)
            renewal = pool.submit(store.renew, "worker-a", claim, 1)
            assert renewal.result(timeout=0.8), "slow hash must not hold the SQLite write lock"
        finally:
            release.set()
        scan.result(timeout=5)
