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


def test_users_listing_is_admin_only_and_safe(tmp_path):
    client, _ = setup(tmp_path)
    with client:
        client.post("/api/v2/dev/session", json={"user_id": "dev-other"})
        assert client.get("/api/v2/admin/users").status_code == 403
        as_admin(client)
        listing = client.get("/api/v2/admin/users").json()
        ids = {item["id"] for item in listing["items"]}
        assert {"dev-user", "dev-other", "dev-admin"} <= ids
        row = next(item for item in listing["items"] if item["id"] == "dev-admin")
        assert row["role"] == "admin" and row["active"] is True
        assert "api_key" not in json.dumps(listing) and "storage_key" not in json.dumps(listing)


def test_role_change_takes_effect_next_request_with_audit(tmp_path):
    client, _ = setup(tmp_path)
    with client:
        as_admin(client)
        changed = client.post("/api/v2/admin/users/dev-user/role", json={"role": "developer", "reason": "转岗开发"}).json()
        assert changed == {"id": "dev-user", "role": "developer"}
        audit = client.get("/api/v2/admin/audit-events").json()
        entry = next(item for item in audit["items"] if item["action"] == "user_role_change")
        assert entry["before"] == {"role": "user"} and entry["after"] == {"role": "developer"}
        assert entry["reason"] == "转岗开发"
        same = client.post("/api/v2/admin/users/dev-user/role", json={"role": "developer"})
        assert same.status_code == 409
        assert same.json()["error"]["code"] == "role_unchanged"
        invalid = client.post("/api/v2/admin/users/dev-user/role", json={"role": "root"})
        assert invalid.status_code == 409
        assert invalid.json()["error"]["code"] == "invalid_role"
        missing = client.post("/api/v2/admin/users/nobody/role", json={"role": "user"})
        assert missing.status_code == 404
        principal = TestClient(create_app(Settings(data_dir=client.app.state.store.root)))
        with principal:
            principal.post("/api/v2/dev/session", json={"user_id": "dev-user"})
            assert principal.get("/api/v2/me").json()["role"] == "developer"


def test_admin_cannot_change_own_role_or_deactivate_self(tmp_path):
    client, _ = setup(tmp_path)
    with client:
        as_admin(client)
        own_role = client.post("/api/v2/admin/users/dev-admin/role", json={"role": "user"})
        assert own_role.status_code == 409
        assert own_role.json()["error"]["code"] == "cannot_change_own_role"
        deactivate = client.post("/api/v2/admin/users/dev-admin/active", json={"active": False})
        assert deactivate.status_code == 409
        assert deactivate.json()["error"]["code"] == "cannot_deactivate_self"


def test_deactivation_blocks_next_request_and_reactivates(tmp_path):
    client, store = setup(tmp_path)
    with client:
        as_admin(client)
        deactivated = client.post("/api/v2/admin/users/dev-other/active", json={"active": False, "reason": "离职"}).json()
        assert deactivated == {"id": "dev-other", "active": False}
        blocked_session = client.post("/api/v2/dev/session", json={"user_id": "dev-other"})
        assert blocked_session.status_code == 404
        forged = TestClient(create_app(Settings(data_dir=store.root)))
        forged.cookies.set("v2_dev_user", "dev-other")
        assert forged.get("/api/v2/me").status_code == 401
        reactivated = client.post("/api/v2/admin/users/dev-other/active", json={"active": True}).json()
        assert reactivated == {"id": "dev-other", "active": True}
        assert forged.post("/api/v2/dev/session", json={"user_id": "dev-other"}).status_code == 200
        audit = client.get("/api/v2/admin/audit-events").json()
        actions = [item["action"] for item in audit["items"]]
        assert actions.count("user_active_change") == 2
        again = client.post("/api/v2/admin/users/dev-other/active", json={"active": True})
        assert again.status_code == 409
        assert again.json()["error"]["code"] == "active_unchanged"
