import pytest

from app.auth.sessions import SessionStore
from app.db.seed import seed_database
from app.security.authorization import ResourcePolicy
from app.security.policies import PolicyConflict, PolicyStore
from scripts.label_equipment import label_equipment


@pytest.fixture
def system(tmp_path):
    path = tmp_path / "business.sqlite3"
    seed_database(path)
    sessions = SessionStore(tmp_path / "access.sqlite3")
    for kind in ("document", "equipment", "alarm", "maintenance"):
        PolicyStore(sessions, resource_kind=kind).initialize()
    for name, role in (("admin", "admin"), ("reader", "engineer")):
        sessions.create_user(name, "test-only-password", role=role, department_id="A", clearance=2)
    return sessions, path


def test_labels_are_explicit_atomic_and_do_not_grant_documents(system):
    sessions, path = system
    token = sessions.login("admin", "test-only-password")
    result = label_equipment(sessions, token, path, "EQ-ROBOT-001", department="A", classification=2)
    assert result == {"equipment": 1, "alarm": 5, "maintenance": 3}
    assert PolicyStore(sessions).list_policies() == []
    for kind in result:
        for policy in PolicyStore(sessions, resource_kind=kind).list_policies():
            assert policy.department_id == "A" and policy.classification == 2
            assert not policy.external_processing_allowed
    assert len(PolicyStore(sessions).audit_events()) == 9
    with pytest.raises(PolicyConflict):
        label_equipment(sessions, token, path, "EQ-ROBOT-001", department="B", classification=0)
    assert len(PolicyStore(sessions).audit_events()) == 9


def test_record_conflict_rolls_back_earlier_equipment_label(system):
    sessions, path = system
    store = PolicyStore(sessions, resource_kind="maintenance")
    store.save(ResourcePolicy(resource_id="M-001-003", department_id="B", classification=2,
                              visibility="department", status="active", policy_version=1,
                              content_version="v1"), expected_version=0, actor_id="test-admin")
    with pytest.raises(PolicyConflict):
        label_equipment(sessions, sessions.login("admin", "test-only-password"), path,
                        "EQ-ROBOT-001", department="A", classification=0)
    assert PolicyStore(sessions, resource_kind="equipment").list_policies() == []
    assert PolicyStore(sessions, resource_kind="alarm").list_policies() == []
    assert len(PolicyStore(sessions).audit_events()) == 1


def test_nonadmin_cannot_import_labels(system):
    sessions, path = system
    with pytest.raises(PermissionError):
        label_equipment(sessions, sessions.login("reader", "test-only-password"), path,
                        "EQ-ROBOT-001", department="A", classification=0)
    assert PolicyStore(sessions, resource_kind="equipment").list_policies() == []
