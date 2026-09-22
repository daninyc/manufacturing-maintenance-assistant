import sqlite3

import pytest

from app.auth.sessions import AuthenticationError, SessionStore


@pytest.fixture
def store(tmp_path):
    value = SessionStore(tmp_path / "access.sqlite3")
    value.initialize()
    return value


def create(store):
    return store.create_user("alice", "test-only-password-123", role="engineer",
                             department_id="A", clearance=2)


def test_login_logout_and_storage_do_not_persist_credentials(store):
    person = create(store)
    token = store.login("alice", "test-only-password-123")
    assert store.authenticate(token) == person
    with store.connect() as connection:
        row = connection.execute("SELECT token_hash FROM sessions").fetchone()
        assert row[0] != token
        row = connection.execute("SELECT password_hash FROM users").fetchone()
        assert row[0] != b"test-only-password-123"
    store.logout(token)
    with pytest.raises(AuthenticationError):
        store.authenticate(token)


@pytest.mark.parametrize("name,password", [
    ("unknown", "test-only-password-123"), ("alice", "incorrect-password"),
    ("' OR 1=1 --", "test-only-password-123"),
])
def test_invalid_login(store, name, password):
    create(store)
    with pytest.raises(AuthenticationError, match="Invalid or expired"):
        store.login(name, password)


def test_expired_and_forged_sessions(store):
    create(store)
    token = store.login("alice", "test-only-password-123", now=100)
    assert store.authenticate(token, now=101).department_id == "A"
    with pytest.raises(AuthenticationError):
        store.authenticate(token, now=3700)
    with pytest.raises(AuthenticationError):
        store.authenticate("forged-token-with-sufficient-length")


def test_disable_and_reenable_never_revives_token(store):
    person = create(store)
    token = store.login("alice", "test-only-password-123")
    changed = store.change_access(person.user_id, role="employee",
                                  department_id="B", clearance=0, active=False)
    assert changed.authz_version == 2
    with pytest.raises(AuthenticationError):
        store.authenticate(token)
    with pytest.raises(AuthenticationError):
        store.login("alice", "test-only-password-123")
    store.change_access(person.user_id, role="employee", department_id="B",
                        clearance=0, active=True)
    with pytest.raises(AuthenticationError):
        store.authenticate(token)
    current = store.authenticate(store.login("alice", "test-only-password-123"))
    assert current.department_id == "B"
    assert current.clearance == 0
    assert current.authz_version == 3


def test_password_change_revokes_sessions(store):
    person = create(store)
    token = store.login("alice", "test-only-password-123")
    store.change_password(person.user_id, "test-only-new-password-456")
    with pytest.raises(AuthenticationError):
        store.authenticate(token)
    with pytest.raises(AuthenticationError):
        store.login("alice", "test-only-password-123")
    assert store.authenticate(store.login("alice", "test-only-new-password-456"))


def test_missing_db_is_not_created(tmp_path):
    path = tmp_path / "missing.sqlite3"
    with pytest.raises(sqlite3.OperationalError):
        SessionStore(path).authenticate("token-with-enough-characters")
    assert not path.exists()


def test_existing_foreign_db_is_rejected(tmp_path):
    path = tmp_path / "foreign.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE preserve_me (value TEXT)")
    with pytest.raises(RuntimeError, match="identity/version"):
        SessionStore(path).initialize()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT name FROM sqlite_master").fetchone()[0] == "preserve_me"


def test_initialize_is_idempotent(store):
    person = create(store)
    store.initialize()
    assert store.authenticate(store.login("alice", "test-only-password-123")) == person


@pytest.mark.parametrize("password", ["short", "x" * 1025])
def test_password_bounds(store, password):
    with pytest.raises(ValueError):
        store.create_user("alice", password, role="engineer", department_id="A", clearance=2)

