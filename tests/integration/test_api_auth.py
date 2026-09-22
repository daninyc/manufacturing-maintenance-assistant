import pytest
from fastapi.testclient import TestClient

from app.api.server import create_app


@pytest.fixture
def system(tmp_path):
    app = create_app(tmp_path / "access.sqlite3")
    app.state.policies.initialize()
    admin = app.state.sessions.create_user(
        "admin", "test-only-admin-password", role="admin", department_id="ADMIN", clearance=2)
    person = app.state.sessions.create_user(
        "alice", "test-only-alice-password", role="engineer", department_id="A", clearance=1)
    return app, TestClient(app), admin, person


def headers(client, name="alice"):
    response = client.post("/api/v1/auth/login", json={
        "username": name, "password": f"test-only-{name}-password"})
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def test_admin_user_list_contains_only_management_fields(system):
    _, client, _, person = system
    url = "/api/v1/admin/users"
    assert client.get(url).status_code == 401
    assert client.get(url, headers=headers(client)).status_code == 403
    auth = headers(client, "admin")
    response = client.get(url + "?limit=1&offset=1", headers=auth)
    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert response.json()["items"] == [person.model_dump() | {"username": "alice"}]
    assert client.get(url + "?limit=51", headers=auth).status_code == 422
    assert client.get(url + "?offset=2", headers=auth).json()["items"] == []


def test_user_list_revoked_before_response_is_not_returned(system, monkeypatch):
    app, client, _, _ = system
    auth = headers(client, "admin")
    original = app.state.sessions.management_page
    def revoke(**kwargs):
        result = original(**kwargs)
        app.state.sessions.logout(auth["Authorization"].removeprefix("Bearer "))
        return result
    monkeypatch.setattr(app.state.sessions, "management_page", revoke)
    response = client.get("/api/v1/admin/users", headers=auth)
    assert response.status_code == 401
    assert "alice" not in response.text


def test_change_own_password_revokes_all_sessions(system):
    app, client, _, _ = system
    first, second = headers(client), headers(client)
    url = "/api/v1/auth/password"
    payload = {"current_password": "test-only-alice-password",
               "new_password": "test-only-replacement-password"}
    assert client.post(url, json=payload).status_code == 401
    wrong = client.post(url, headers=first, json=payload | {"current_password": "wrong"})
    assert wrong.status_code == 401
    assert app.state.policies.audit_events() == []
    assert client.get("/api/v1/me", headers=first).status_code == 200
    assert client.post(url, headers=first, json=payload | {"user_id": "admin"}).status_code == 422
    assert client.post(url, headers=first, json=payload).status_code == 200
    for auth in (first, second):
        assert client.get("/api/v1/me", headers=auth).status_code == 401
    assert client.post("/api/v1/auth/login", json={"username": "alice",
        "password": payload["current_password"]}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"username": "alice",
        "password": payload["new_password"]}).status_code == 200
    events = app.state.policies.audit_events()
    assert len(events) == 1 and events[0]["action"] == "user.password"
    assert "password" not in str(events[0].get("resource_id"))


def test_http_login_me_logout(system):
    _, client, _, _ = system
    assert client.get("/api/v1/me").status_code == 401
    auth = headers(client)
    result = client.get("/api/v1/me", headers=auth)
    assert result.json()["department_id"] == "A"
    assert result.headers["cache-control"] == "no-store"
    assert "password" not in result.text
    assert client.post("/api/v1/auth/logout", headers=auth).status_code == 200
    assert client.get("/api/v1/me", headers=auth).status_code == 401


def test_client_cannot_assign_identity_or_read_admin_data(system):
    _, client, _, _ = system
    response = client.post("/api/v1/auth/login", json={
        "username": "alice", "password": "SECRET_SHOULD_NOT_ECHO", "role": "admin"})
    assert response.status_code == 422
    assert "SECRET_SHOULD_NOT_ECHO" not in response.text
    assert client.get("/health/ready", headers=headers(client)).status_code == 403


def test_rate_limit(system):
    _, client, _, _ = system
    for _ in range(10):
        assert client.post("/api/v1/auth/login", json={
            "username": "absent", "password": "incorrect"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={
        "username": "absent", "password": "incorrect"}).status_code == 429


def test_policy_authority_and_conflicts(system):
    app, client, _, _ = system
    admin_auth = headers(client, "admin")
    payload = {"expected_version": 0, "policy": {
        "resource_id": "docA", "department_id": "A", "visibility": "department",
        "classification": 1, "status": "active", "policy_version": 1,
        "content_version": "v1"}}
    url = "/api/v1/admin/documents/docA/policy"
    assert client.patch(url, json=payload, headers=headers(client)).status_code == 403
    assert client.patch(url, json=payload, headers=admin_auth).status_code == 200
    assert client.patch(url, json=payload, headers=admin_auth).status_code == 409
    assert len(client.get("/api/v1/documents", headers=headers(client)).json()) == 1
    assert client.get("/api/v1/documents", headers=admin_auth).json() == []
    assert len(app.state.policies.audit_events()) == 1
    payload["expected_version"] = 1
    payload["policy"].update(status="disabled", policy_version=2)
    assert client.patch(url, json=payload, headers=admin_auth).status_code == 200
    assert client.get("/api/v1/documents", headers=headers(client)).json() == []


def test_admin_change_revokes_existing_session(system):
    _, client, _, person = system
    old = headers(client)
    response = client.patch("/api/v1/admin/users/" + person.user_id,
                            headers=headers(client, "admin"), json={
                                "role": "employee", "department_id": "B",
                                "clearance": 0, "active": True})
    assert response.status_code == 200
    assert client.get("/api/v1/me", headers=old).status_code == 401
    assert client.get("/api/v1/me", headers=headers(client)).json()["department_id"] == "B"


def test_missing_database_is_controlled(tmp_path):
    client = TestClient(create_app(tmp_path / "missing.sqlite3"))
    assert client.get("/health/live").status_code == 200
    result = client.post("/api/v1/auth/login", json={"username": "x", "password": "y"})
    assert result.status_code == 503
    assert not (tmp_path / "missing.sqlite3").exists()


@pytest.mark.parametrize("operation", ["create-user", "change-user", "policy", "business-policy"])
def test_admin_revoked_after_dependency_check_cannot_write(system, monkeypatch, operation):
    app, client, admin, person = system
    auth = headers(client, "admin")
    def revoke():
        app.state.sessions.change_access(admin.user_id, role="employee", department_id="ADMIN",
                                         clearance=2, active=True)
    if operation == "create-user":
        original = app.state.sessions.create_user
        def intercepted(*args, **kwargs):
            revoke()
            return original(*args, **kwargs)
        monkeypatch.setattr(app.state.sessions, "create_user", intercepted)
        response = client.post("/api/v1/admin/users", headers=auth, json={
            "username": "must-not-exist", "password": "test-only-long-password",
            "role": "employee", "department_id": "A", "clearance": 0})
        with app.state.sessions.connect() as db:
            assert db.execute("SELECT 1 FROM users WHERE username='must-not-exist'").fetchone() is None
    elif operation == "change-user":
        original = app.state.sessions.change_access
        def intercepted(*args, **kwargs):
            original(admin.user_id, role="employee", department_id="ADMIN",
                     clearance=2, active=True)
            return original(*args, **kwargs)
        monkeypatch.setattr(app.state.sessions, "change_access", intercepted)
        response = client.patch("/api/v1/admin/users/" + person.user_id, headers=auth, json={
            "role": "admin", "department_id": "B", "clearance": 2, "active": False})
        with app.state.sessions.connect() as db:
            row = db.execute("SELECT role, department_id, clearance, active, authz_version "
                             "FROM users WHERE user_id=?", (person.user_id,)).fetchone()
        assert tuple(row) == (person.role, person.department_id, person.clearance,
                              int(person.active), person.authz_version)
    else:
        target = (app.state.policies if operation == "policy"
                  else app.state.business.stores["equipment"])
        target.initialize()
        original = target.save
        def intercepted(*args, **kwargs):
            revoke()
            return original(*args, **kwargs)
        monkeypatch.setattr(target, "save", intercepted)
        url = ("/api/v1/admin/documents/blocked/policy" if operation == "policy"
               else "/api/v1/admin/resources/equipment/blocked/policy")
        response = client.patch(url, headers=auth, json={
            "expected_version": 0, "policy": {"resource_id": "blocked", "department_id": "A",
                "classification": 0, "visibility": "department", "status": "draft",
                "policy_version": 1, "content_version": "v1"}})
        assert target.get_many(["blocked"]) == {}
    assert response.status_code == 401
    assert app.state.policies.audit_events() == []


def test_ready_requires_upgraded_policy_and_business_databases(tmp_path):
    from app.db.seed import seed_database

    path = tmp_path / "business.sqlite3"
    app = create_app(tmp_path / "access.sqlite3", path)
    app.state.policies.initialize()
    app.state.sessions.create_user("admin", "test-only-admin-password", role="admin",
                                  department_id="A", clearance=2)
    client = TestClient(app)
    assert client.get("/health/ready").status_code == 401
    auth = headers(client, "admin")
    assert client.get("/health/ready", headers=auth).status_code == 503
    for store in app.state.business.stores.values():
        store.initialize()
    response = client.get("/health/ready", headers=auth)
    assert response.status_code == 503 and not path.exists()
    assert str(path) not in response.text
    seed_database(path)
    response = client.get("/health/ready", headers=auth)
    assert response.status_code == 200
    assert response.json()["scope"] == "authentication-policy-business-databases"
    assert "cloud-model" in response.json()["not_checked"]
    assert app.state.vector_store is None
