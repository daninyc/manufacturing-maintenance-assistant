import sqlite3
from contextlib import closing

import pytest

from app.auth.sessions import SessionStore
from app.security.policies import PolicyStore
from scripts.upgrade_access import upgrade_access


def test_upgrade_preserves_sessions_and_creates_no_grants(tmp_path):
    path = tmp_path / "access.sqlite3"
    sessions = SessionStore(path)
    PolicyStore(sessions).initialize()
    user = sessions.create_user("alice", "test-only-password", role="engineer",
                                department_id="A", clearance=1)
    token = sessions.login("alice", "test-only-password")
    backup = upgrade_access(path)
    assert backup.exists()
    assert SessionStore(backup).authenticate(token) == user
    assert sessions.authenticate(token) == user
    for kind in ("equipment", "alarm", "maintenance"):
        assert PolicyStore(sessions, resource_kind=kind).list_policies() == []
    second = upgrade_access(path)
    assert second != backup and backup.exists()
    assert sessions.authenticate(token) == user


def test_upgrade_rejects_foreign_or_missing_database(tmp_path):
    path = tmp_path / "other.sqlite3"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE personal(note TEXT)")
    with pytest.raises(RuntimeError):
        upgrade_access(path)
    with pytest.raises(sqlite3.OperationalError):
        upgrade_access(tmp_path / "missing.sqlite3")
    assert list(tmp_path.glob("*.bak")) == []
    assert not (tmp_path / "missing.sqlite3").exists()
