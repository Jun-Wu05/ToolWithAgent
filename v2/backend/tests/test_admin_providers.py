import json

from fastapi.testclient import TestClient

from toolwithagent_v2.api.app import create_app
from toolwithagent_v2.settings import Settings


def setup(tmp_path, development=True):
    settings = Settings(data_dir=tmp_path / "data", development=development)
    app = create_app(settings)
    return TestClient(app), app.state.store


def as_admin(client):
    assert client.post("/api/v2/dev/session", json={"user_id": "dev-admin"}).status_code == 200


def test_providers_role_fenced(tmp_path):
    client, _ = setup(tmp_path)
    with client:
        client.post("/api/v2/dev/session", json={"user_id": "dev-other"})
        for response in (
            client.get("/api/v2/admin/providers"),
            client.get("/api/v2/admin/providers/openai/history"),
            client.put("/api/v2/admin/providers/openai", json={"model": "gpt-4o-mini", "api_key": "sk-x"}),
            client.post("/api/v2/admin/providers/openai/test", json={}),
        ):
            assert response.status_code == 403


def test_provider_versions_are_immutable_and_secrets_never_echo(tmp_path):
    client, store = setup(tmp_path)
    with client:
        as_admin(client)
        first = client.put("/api/v2/admin/providers/openai", json={"model": "gpt-4o-mini", "api_key": "sk-first-key", "reason": "初始配置"}).json()
        assert first == {"provider": "openai", "revision": 1, "model": "gpt-4o-mini"}
        second = client.put("/api/v2/admin/providers/openai", json={"model": "gpt-4o", "api_key": "sk-second-key"}).json()
        assert second["revision"] == 2
        listing = client.get("/api/v2/admin/providers").json()
        row = next(item for item in listing["items"] if item["provider"] == "openai")
        assert row["revision"] == 2 and row["model"] == "gpt-4o" and row["has_secret"] is True
        assert "api_key" not in row and "sk-" not in json.dumps(listing)
        history = client.get("/api/v2/admin/providers/openai/history").json()
        assert [item["revision"] for item in history["items"]] == [2, 1]
        assert all("api_key" not in item and "sk-" not in json.dumps(item) for item in history["items"])
        audit = client.get("/api/v2/admin/audit-events").json()
        serialized = json.dumps(audit, ensure_ascii=False)
        assert "sk-first-key" not in serialized and "sk-second-key" not in serialized
        entry = next(item for item in audit["items"] if item["action"] == "provider_update" and item["after"]["revision"] == 2)
        assert entry["after"]["model"] == "gpt-4o" and "sk-" not in json.dumps(entry)


def test_frozen_revision_still_resolves_after_rotation(tmp_path):
    client, store = setup(tmp_path)
    with client:
        as_admin(client)
        client.put("/api/v2/admin/providers/deepseek", json={"model": "deepseek-chat", "api_key": "sk-old"})
        client.put("/api/v2/admin/providers/deepseek", json={"model": "deepseek-reasoner", "api_key": "sk-new"})
        frozen = store.resolve_provider_secret("deepseek", revision=1)
        assert frozen == {"model": "deepseek-chat", "params": {}, "api_key": "sk-old"}
        current = store.resolve_provider_secret("deepseek")
        assert current["api_key"] == "sk-new" and current["model"] == "deepseek-reasoner"


def test_missing_master_key_fails_closed_in_production(tmp_path, monkeypatch):
    import os
    monkeypatch.delenv("V2_MASTER_KEY", raising=False)
    client, store = setup(tmp_path, development=False)
    client.cookies.set("v2_dev_user", "dev-admin")
    denied = client.put("/api/v2/admin/providers/openai", json={"model": "gpt-4o-mini", "api_key": "sk-x"})
    assert denied.status_code == 503
    assert denied.json()["error"]["code"] == "master_key_missing"
    assert not (tmp_path / "data" / "master.key").exists()


def test_wrong_master_key_is_detected_not_garbled(tmp_path):
    client, store = setup(tmp_path)
    with client:
        as_admin(client)
        client.put("/api/v2/admin/providers/openai", json={"model": "gpt-4o-mini", "api_key": "sk-keep"})
    from toolwithagent_v2.infrastructure.store import Store
    from toolwithagent_v2.infrastructure.providers import MasterKeyUnavailable
    rotated = Store(Settings(data_dir=tmp_path / "data"))
    rotated._cached_master_key = b"x" * 32
    try:
        rotated.resolve_provider_secret("openai")
        raise AssertionError("expected master_key_invalid")
    except MasterKeyUnavailable as exc:
        assert str(exc) == "master_key_invalid"


def test_connection_test_creates_no_task_or_run(tmp_path, monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200

    class FakeClient:
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, headers=None):
            captured["url"] = url
            captured["auth"] = headers.get("Authorization")
            return FakeResponse()

    import httpx
    monkeypatch.setattr(httpx, "Client", FakeClient)
    client, store = setup(tmp_path)
    with client:
        as_admin(client)
        result = client.post("/api/v2/admin/providers/openai/test", json={"api_key": "sk-adhoc"}).json()
        assert result["ok"] is True and result["status_code"] == 200 and "latency_ms" in result
        assert captured["url"] == "https://api.openai.com/v1/models"
        assert captured["auth"] == "Bearer sk-adhoc"
        runs = client.get("/api/v2/admin/runs").json()
        assert runs["total"] == 0
        audit = client.get("/api/v2/admin/audit-events").json()
        assert not any(item["action"].startswith("provider") for item in audit["items"])
        assert "sk-adhoc" not in json.dumps(audit)


def test_unknown_provider_and_invalid_input(tmp_path):
    client, _ = setup(tmp_path)
    with client:
        as_admin(client)
        unknown = client.put("/api/v2/admin/providers/unknown", json={"model": "m", "api_key": "k"})
        assert unknown.status_code == 404
        assert unknown.json()["error"]["code"] == "provider_not_found"
        blank = client.put("/api/v2/admin/providers/openai", json={"model": "  ", "api_key": "k"})
        assert blank.status_code == 400
        assert blank.json()["error"]["code"] == "invalid_provider_input"
        no_key = client.put("/api/v2/admin/providers/openai", json={"model": "gpt-4o-mini", "api_key": ""})
        assert no_key.status_code == 400
