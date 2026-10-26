from io import BytesIO
from pathlib import Path
import hashlib
import json
import sqlite3
import zipfile

from openpyxl import Workbook

from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile

from toolwithagent_v2.api.app import create_app
from toolwithagent_v2.infrastructure.db import connect
from toolwithagent_v2.infrastructure.store import Store
from toolwithagent_v2.runtime.worker import Worker
from toolwithagent_v2.settings import Settings


def setup(tmp_path):
    settings = Settings(data_dir=tmp_path / "data")
    app = create_app(settings)
    return TestClient(app), app.state.store


def test_migration_and_restart(tmp_path):
    client, store = setup(tmp_path)
    with client:
        created = client.post("/api/v2/conversations", json={"title": "一次会话"}).json()
        uploaded = client.post(f"/api/v2/conversations/{created['id']}/files", files={"file": ("sample.csv", b"a,b\n1,2\n")}).json()
        assert uploaded["run"]["status"] == "queued"
        assert not any("\\\\" in value or str(tmp_path) in value for value in [uploaded["file"].get("name", ""), json.dumps(uploaded)])
    client2 = TestClient(create_app(Settings(data_dir=store.root)))
    detail = client2.get(f"/api/v2/conversations/{created['id']}").json()
    assert detail["files"][0]["sha256"] == hashlib.sha256(b"a,b\n1,2\n").hexdigest()
    assert detail["runs"][0]["status"] == "queued"
    with connect(store.path) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0007_admin_console"
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_owner_isolation_and_errors(tmp_path):
    client, _ = setup(tmp_path)
    conversation = client.post("/api/v2/conversations", json={}).json()
    client.post("/api/v2/dev/session", json={"user_id": "dev-other"})
    for response in (
        client.get(f"/api/v2/conversations/{conversation['id']}"),
        client.post(f"/api/v2/conversations/{conversation['id']}/files", files={"file": ("x.csv", b"a")}),
        client.get(f"/api/v2/conversations/{conversation['id']}/events?after=0"),
    ):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "conversation_not_found"
        assert response.json()["error"]["request_id"]


def test_fifo_leader_and_outbox(tmp_path):
    client, store = setup(tmp_path)
    conversation = client.post("/api/v2/conversations", json={}).json()
    first = client.post(f"/api/v2/conversations/{conversation['id']}/files", files={"file": ("first.txt", b"first")}).json()
    second = client.post(f"/api/v2/conversations/{conversation['id']}/files", files={"file": ("second.txt", b"second")}).json()
    worker = Worker(store, "worker-one")
    assert worker.once()
    assert client.get(f"/api/v2/runs/{first['run']['id']}").json()["status"] == "succeeded"
    assert client.get(f"/api/v2/runs/{second['run']['id']}").json()["status"] == "queued"
    assert not Worker(store, "worker-two").once()
    assert worker.once()
    events = store.events("dev-user", conversation["id"], 0)
    assert [e["sequence"] for e in events] == list(range(1, len(events) + 1))
    assert store.events("dev-user", conversation["id"], events[2]["sequence"]) == events[3:]
    assert events[-1]["payload"]["status"] == "succeeded"


def test_corrupt_file_fails_without_artifact(tmp_path):
    client, store = setup(tmp_path)
    conversation = client.post("/api/v2/conversations", json={}).json()
    uploaded = client.post(f"/api/v2/conversations/{conversation['id']}/files", files={"file": ("x.txt", b"abc")}).json()
    with connect(store.path) as db:
        key = db.execute("SELECT storage_key FROM files WHERE id=?", (uploaded["file"]["id"],)).fetchone()[0]
    (store.root / key).write_bytes(b"wrong")
    assert Worker(store, "worker-one").once()
    run = client.get(f"/api/v2/runs/{uploaded['run']['id']}").json()
    assert run["status"] == "failed"
    assert run["error_code"] == "file_hash_mismatch"
    with connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 0


def test_upload_validation_and_no_path_leak(tmp_path):
    client, store = setup(tmp_path)
    conversation = client.post("/api/v2/conversations", json={}).json()
    response = client.post(f"/api/v2/conversations/{conversation['id']}/files", files={"file": ("../../bad.exe", b"abc")})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_file_type"
    assert str(tmp_path) not in response.text
    small = TestClient(create_app(Settings(data_dir=tmp_path / "small", max_upload_bytes=2)))
    new_conversation = small.post("/api/v2/conversations", json={}).json()
    response = small.post(f"/api/v2/conversations/{new_conversation['id']}/files", files={"file": ("x.csv", b"abc")})
    assert response.status_code == 413


def test_production_has_no_dev_routes(tmp_path):
    client = TestClient(create_app(Settings(data_dir=tmp_path / "prod", development=False)))
    assert client.get("/api/v2/dev/identities").status_code == 404
    assert client.get("/api/v2/me").status_code == 401


def test_package_boundaries():
    root = Path(__file__).resolve().parents[3]
    for folder in ("application", "contracts", "agent"):
        for file in (root / folder).rglob("*.py"):
            assert "toolwithagent_v2" not in file.read_text(encoding="utf-8")
    for file in (root / "v2/backend/toolwithagent_v2").rglob("*.py"):
        assert "from web" not in file.read_text(encoding="utf-8")
        assert "import web" not in file.read_text(encoding="utf-8")


def test_upload_and_message_idempotency(tmp_path):
    client, store = setup(tmp_path)
    conversation = client.post("/api/v2/conversations", json={}).json()
    url = f"/api/v2/conversations/{conversation['id']}"
    headers = {"Idempotency-Key": "upload-1"}
    first = client.post(url + "/files", files={"file": ("a.csv", b"a,b\n1,2")}, headers=headers)
    repeated = client.post(url + "/files", files={"file": ("a.csv", b"a,b\n1,2")}, headers=headers)
    assert first.status_code == repeated.status_code == 201
    assert first.json() == repeated.json()
    conflict = client.post(url + "/files", files={"file": ("a.csv", b"different")}, headers=headers)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_key_reused"
    headers = {"Idempotency-Key": "message-1"}
    first = client.post(url + "/messages", json={"content": "hello"}, headers=headers)
    repeated = client.post(url + "/messages", json={"content": "hello"}, headers=headers)
    assert first.json() == repeated.json()
    assert client.post(url + "/messages", json={"content": "new"}, headers=headers).status_code == 409
    with connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 2
        assert first.json()["run"]["status"] == "queued"
        assert db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM idempotency_receipts").fetchone()[0] == 2


def test_sse_route_frames_replay_after_cursor(tmp_path):
    import asyncio
    from types import SimpleNamespace
    client, store = setup(tmp_path)
    conversation = client.post("/api/v2/conversations", json={}).json()
    client.post(f"/api/v2/conversations/{conversation['id']}/messages", json={"content": "hello"})
    endpoint = next(route.endpoint for route in client.app.routes if getattr(route, "path", None) == "/api/v2/conversations/{conversation_id}/events")

    async def replay(after):
        async def connected():
            return False
        request = SimpleNamespace(cookies={}, is_disconnected=connected)
        response = await endpoint(request, conversation["id"], after)
        frame = await asyncio.wait_for(response.body_iterator.__anext__(), timeout=2)
        await response.body_iterator.aclose()
        return frame

    first = asyncio.run(replay(0))
    second = asyncio.run(replay(1))
    assert first.startswith("id: 1\ndata: ")
    assert second.startswith("id: 2\ndata: ")
    assert "event:" not in second
    data = json.loads(second.split("data: ", 1)[1])
    assert data["event_type"] == "message_created"
    assert data["sequence"] == 2


def test_queued_run_survives_worker_restart(tmp_path):
    client, store = setup(tmp_path)
    conversation = client.post("/api/v2/conversations", json={}).json()
    uploaded = client.post(f"/api/v2/conversations/{conversation['id']}/files", files={"file": ("a.txt", b"hello")}).json()
    fresh_store = Store(Settings(data_dir=store.root))
    assert Worker(fresh_store, "new-worker-process").once()
    assert client.get(f"/api/v2/runs/{uploaded['run']['id']}").json()["status"] == "succeeded"


def test_developer_cannot_write(tmp_path):
    client, _ = setup(tmp_path)
    client.post("/api/v2/dev/session", json={"user_id": "dev-other"})
    assert client.get("/api/v2/me").json()["role"] == "developer"
    response = client.post("/api/v2/conversations", json={})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "insufficient_capability"


def test_expired_run_is_failed_before_next_worker_claim(tmp_path):
    client, store = setup(tmp_path)
    conversation = client.post("/api/v2/conversations", json={}).json()
    url = f"/api/v2/conversations/{conversation['id']}/files"
    first = client.post(url, files={"file": ("first.txt", b"first")}).json()
    second = client.post(url, files={"file": ("second.txt", b"second")}).json()
    old_claim = store.claim("lost-worker")
    assert old_claim["id"] == first["run"]["id"]
    with connect(store.path) as db:
        db.execute("UPDATE worker_leases SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE id='v2-primary'")
        db.execute("UPDATE runs SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE id=?", (old_claim["id"],))
        db.commit()

    assert Worker(Store(Settings(data_dir=store.root)), "replacement-worker").once()
    assert store.get_run("dev-user", first["run"]["id"])["error_code"] == "worker_lost"
    assert store.get_run("dev-user", second["run"]["id"])["status"] == "succeeded"
    assert not store.finish("lost-worker", old_claim)
    events = store.events("dev-user", conversation["id"], 0)
    assert any(e["event_type"] == "run_failed" and e["payload"]["error_code"] == "worker_lost" for e in events)


def test_file_read_race_fails_run_without_killing_worker(tmp_path, monkeypatch):
    client, store = setup(tmp_path)
    conversation = client.post("/api/v2/conversations", json={}).json()
    uploaded = client.post(f"/api/v2/conversations/{conversation['id']}/files", files={"file": ("file.txt", b"content")}).json()
    with connect(store.path) as db:
        target = (store.root / db.execute("SELECT storage_key FROM files WHERE id=?", (uploaded["file"]["id"],)).fetchone()[0]).resolve()
    real_open = Path.open

    def inaccessible(path, *args, **kwargs):
        if path.resolve() == target and args and args[0] == "rb":
            raise PermissionError("file became inaccessible")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", inaccessible)
    assert Worker(store, "worker-one").once()
    run = store.get_run("dev-user", uploaded["run"]["id"])
    assert run["status"] == "failed"
    assert run["error_code"] == "file_unreadable"
    assert store.get_conversation("dev-user", conversation["id"])["files"][0]["parse_status"] == "failed"


def test_slow_validation_renews_lease(tmp_path, monkeypatch):
    import threading
    import time

    client, store = setup(tmp_path)
    conversation = client.post("/api/v2/conversations", json={}).json()
    uploaded = client.post(f"/api/v2/conversations/{conversation['id']}/files", files={"file": ("file.txt", b"content")}).json()
    worker = Worker(store, "slow-worker", lease_seconds=0.3)
    entered = threading.Event()
    release = threading.Event()
    result = []

    def slow_validate(_snapshot):
        entered.set()
        assert release.wait(timeout=3)
        return None

    monkeypatch.setattr(worker, "_validate", slow_validate)
    thread = threading.Thread(target=lambda: result.append(worker.once()))
    thread.start()
    try:
        assert entered.wait(timeout=2)
        time.sleep(0.65)
        assert store.claim("other-worker") is None
    finally:
        release.set()
        thread.join(timeout=3)
    assert result == [True]
    assert store.get_run("dev-user", uploaded["run"]["id"])["status"] == "succeeded"


def test_xlsx_validation_rejects_arbitrary_zip(tmp_path):
    client, store = setup(tmp_path)
    conversation = client.post("/api/v2/conversations", json={}).json()
    url = f"/api/v2/conversations/{conversation['id']}/files"

    workbook = Workbook()
    workbook.active.append(["name", "value"])
    workbook.active.append(["valid", 1])
    valid_content = BytesIO()
    workbook.save(valid_content)
    valid = client.post(url, files={"file": ("valid.xlsx", valid_content.getvalue())}).json()

    arbitrary_zip = BytesIO()
    with zipfile.ZipFile(arbitrary_zip, "w") as archive:
        archive.writestr("random.txt", "not a workbook")
    invalid = client.post(url, files={"file": ("fake.xlsx", arbitrary_zip.getvalue())}).json()

    worker = Worker(store, "xlsx-worker")
    assert worker.once()
    assert store.get_run("dev-user", valid["run"]["id"])["status"] == "succeeded"
    assert worker.once()
    failed = store.get_run("dev-user", invalid["run"]["id"])
    assert failed["status"] == "failed"
    assert failed["error_code"] == "invalid_file_content"
    with connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 0
