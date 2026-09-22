import pytest
from fastapi.testclient import TestClient

from app.api.server import create_app
from app.retrieval.vector_store import LocalChromaStore
from app.security.authorization import ResourcePolicy


@pytest.fixture
def upload(tmp_path):
    app = create_app(tmp_path / "access.sqlite3")
    app.state.policies.initialize()
    sessions = app.state.sessions
    admin = sessions.create_user("admin", "test-only-admin-password", role="admin",
                                 department_id="A", clearance=2)
    sessions.create_user("reader", "test-only-reader-password", role="employee",
                         department_id="A", clearance=1)
    app.state.policies.save(ResourcePolicy(resource_id="DOC", department_id="A",
        visibility="department", classification=1, status="draft", policy_version=1,
        content_version="pending"), expected_version=0, actor_id=admin.user_id)
    app.state.vector_store = LocalChromaStore(tmp_path / "chroma", "upload_test")
    auth = {"Authorization": "Bearer " + sessions.login("admin", "test-only-admin-password"),
            "Content-Type": "text/plain"}
    return app, TestClient(app), auth, tmp_path


URL = "/api/v1/admin/documents/DOC/content?expected_version=1&format=txt"


def test_admin_can_list_draft_metadata_without_read_access(upload):
    app, client, auth, _ = upload
    url = "/api/v1/admin/documents"
    assert client.get(url).status_code == 401
    reader = {"Authorization": "Bearer " + app.state.sessions.login(
        "reader", "test-only-reader-password")}
    assert client.get(url, headers=reader).status_code == 403
    response = client.get(url + "?limit=1", headers=auth)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1 and data["items"][0]["status"] == "draft"
    assert set(data["items"][0]) == set(ResourcePolicy.model_fields)
    assert client.get(url + "?offset=1", headers=auth).json()["items"] == []
    assert client.get(url + "?limit=51", headers=auth).status_code == 422
    assert client.get("/api/v1/documents", headers=auth).json() == []


def test_admin_metadata_rechecks_revocation(upload, monkeypatch):
    app, client, auth, _ = upload
    original = app.state.policies.management_page
    token = auth["Authorization"].removeprefix("Bearer ")
    def revoke(**kwargs):
        result = original(**kwargs)
        app.state.sessions.logout(token)
        return result
    monkeypatch.setattr(app.state.policies, "management_page", revoke)
    response = client.get("/api/v1/admin/documents", headers=auth)
    assert response.status_code == 401
    assert "DOC" not in response.text


def test_upload_publishes_and_protects_original(upload):
    app, client, auth, directory = upload
    result = client.post(URL, content=b"SIMULATED_SOP", headers=auth)
    assert result.status_code == 201, result.text
    assert result.json()["status"] == "active"
    assert result.json()["policy_version"] == 3
    assert str(directory) not in result.text
    originals = list((directory / "uploads").iterdir())
    assert len(originals) == 1 and originals[0].read_bytes() == b"SIMULATED_SOP"
    assert client.get("/uploads/" + originals[0].name, headers=auth).status_code == 404
    reader = {"Authorization": "Bearer " + app.state.sessions.login(
        "reader", "test-only-reader-password")}
    chunk = app.state.vector_store.collection.get()["ids"][0]
    assert client.get(f"/api/v1/documents/DOC/chunks/{chunk}", headers=reader).json()[
        "excerpt"] == "SIMULATED_SOP"
    assert client.post(URL, content=b"OVERWRITE", headers=auth).status_code == 409


@pytest.mark.parametrize("case,expected", [("anonymous", 401), ("reader", 403),
    ("media", 415), ("oversize", 413), ("empty", 422), ("encoding", 422)])
def test_invalid_upload_never_publishes(upload, case, expected):
    app, client, auth, directory = upload
    body = b"VALID"
    if case == "anonymous":
        auth = {}
    elif case == "reader":
        auth["Authorization"] = "Bearer " + app.state.sessions.login(
            "reader", "test-only-reader-password")
    elif case == "media":
        auth["Content-Type"] = "application/zip"
    elif case == "oversize":
        auth["Content-Length"] = str(10 * 1024 * 1024 + 1)
    elif case == "empty":
        body = b""
    else:
        body = b"\xff\xfe"
    response = client.post(URL, content=body, headers=auth)
    assert response.status_code == expected, response.text
    assert app.state.policies.get_many(["DOC"])["DOC"].status == "draft"
    assert app.state.vector_store.collection.count() == 0
    assert not list((directory / "uploads").glob("*"))


def test_upload_without_length_enforces_actual_bytes(upload):
    app, client, auth, directory = upload
    response = client.post(URL, headers=auth,
                           content=iter([b"x" * (10 * 1024 * 1024), b"x"]))
    assert "content-length" not in response.request.headers
    assert response.status_code == 413
    assert app.state.policies.get_many(["DOC"])["DOC"].status == "draft"
    assert not list((directory / "uploads").glob("*"))


def test_revocation_while_receiving_prevents_file_creation(upload, monkeypatch):
    from starlette.requests import Request

    app, client, auth, directory = upload
    original = Request.stream
    token = auth["Authorization"].removeprefix("Bearer ")
    admin = app.state.sessions.authenticate(token)
    async def revoked_stream(request):
        async for part in original(request):
            app.state.sessions.change_access(admin.user_id, role="employee",
                department_id="A", clearance=2, active=True)
            yield part
    monkeypatch.setattr(Request, "stream", revoked_stream)
    response = client.post(URL, content=b"DO_NOT_PUBLISH", headers=auth)
    assert response.status_code == 401
    assert app.state.policies.get_many(["DOC"])["DOC"].status == "draft"
    assert app.state.vector_store.collection.count() == 0
    assert not list((directory / "uploads").glob("*"))


def test_index_failure_cleans_uploaded_file(upload, monkeypatch):
    app, client, auth, directory = upload
    def failed_index(**kwargs):
        raise RuntimeError("SIMULATED_INTERNAL_PATH_AND_SECRET")
    monkeypatch.setattr(app.state.vector_store, "upsert", failed_index)
    response = client.post(URL, content=b"SIMULATED_SOP", headers=auth)
    assert response.status_code == 503
    assert "SIMULATED_INTERNAL" not in response.text
    assert app.state.policies.get_many(["DOC"])["DOC"].status == "failed"
    assert not list((directory / "uploads").glob("*"))
