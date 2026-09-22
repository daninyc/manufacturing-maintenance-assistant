from datetime import timedelta, timezone

import pytest

from app.auth.sessions import SessionStore
from app.db.repositories import MaintenanceRepository
from app.db.seed import seed_database
from app.security.authorization import ResourcePolicy
from app.services.protected_data import ProtectedMaintenance, ResourceUnavailable


@pytest.fixture
def system(tmp_path):
    business = tmp_path / "business.sqlite3"
    seed_database(business)
    sessions = SessionStore(tmp_path / "access.sqlite3")
    service = ProtectedMaintenance(business, sessions)
    for store in service.stores.values():
        store.initialize()
    sessions.create_user("alice", "test-only-password", role="engineer",
                         department_id="A", clearance=1)
    return service, sessions.login("alice", "test-only-password")


def label(service, kind, resource_id, department="A", classification=1):
    service.stores[kind].save(ResourcePolicy(
        resource_id=resource_id, department_id=department, visibility="department",
        classification=classification, status="active", policy_version=1,
        content_version="simulation-v1"), expected_version=0, actor_id="test-admin")


def test_equipment_missing_cross_department_and_clearance_deny(system):
    service, token = system
    with pytest.raises(ResourceUnavailable):
        service.query(token, "equipment", "EQ-ROBOT-001")
    label(service, "equipment", "EQ-ROBOT-001", "B")
    label(service, "equipment", "EQ-ROBOT-002", classification=2)
    for equipment in ("EQ-ROBOT-001", "EQ-ROBOT-002", "MISSING"):
        with pytest.raises(ResourceUnavailable):
            service.query(token, "equipment", equipment)


@pytest.mark.parametrize("operation,kind", [("alarms", "alarm"), ("maintenance", "maintenance")])
def test_record_and_document_labels_required_before_limit(system, operation, kind):
    service, token = system
    equipment = "EQ-ROBOT-001"
    label(service, "equipment", equipment)
    assert service.query(token, operation, equipment) == []
    repository = MaintenanceRepository(service.path)
    rows = (repository.list_recent_alarms(equipment) if operation == "alarms"
            else repository.list_maintenance_history(equipment))
    selected = rows[-1]
    record_id = selected.alarm_id if kind == "alarm" else selected.record_id
    label(service, kind, record_id)
    assert service.query(token, operation, equipment) == []
    label(service, "document", selected.document_id)
    result = service.query(token, operation, equipment, limit=1)
    assert result == [selected]  # newer unlabelled records cannot starve this result
    assert service.stores["document"].get_many([record_id]) == {}


def test_record_cannot_override_forbidden_document(system):
    service, token = system
    label(service, "equipment", "EQ-ROBOT-001")
    row = MaintenanceRepository(service.path).list_recent_alarms("EQ-ROBOT-001", 1)[0]
    label(service, "alarm", row.alarm_id)
    label(service, "document", row.document_id, "B")
    assert service.query(token, "alarms", "EQ-ROBOT-001") == []


@pytest.mark.parametrize("operation,kind", [("alarms", "alarm"), ("maintenance", "maintenance")])
def test_time_range_is_applied_before_limit(system, operation, kind):
    service, token = system
    equipment = "EQ-ROBOT-001"
    label(service, "equipment", equipment)
    repository = MaintenanceRepository(service.path)
    rows = (repository.list_recent_alarms(equipment) if operation == "alarms"
            else repository.list_maintenance_history(equipment))
    documents = set()
    for row in rows:
        label(service, kind, row.alarm_id if kind == "alarm" else row.record_id)
        if row.document_id not in documents:
            label(service, "document", row.document_id)
            documents.add(row.document_id)
    selected = rows[-1]
    when = selected.occurred_at if kind == "alarm" else selected.maintained_at
    offset_time = when.astimezone(timezone(timedelta(hours=8)))
    assert service.query(token, operation, equipment, limit=1,
                         start_time=offset_time, end_time=offset_time) == [selected]
    assert service.query(token, operation, equipment,
                         end_time=when - timedelta(seconds=1)) == []


def test_diagnosis_rejects_ambiguous_time_and_forged_identity():
    from pydantic import ValidationError

    from app.schemas.diagnosis import DiagnoseRequest
    for extra in ({"start_time": "2026-01-01T00:00:00"}, {"role": "admin"},
                  {"start_time": "2026-02-01T00:00:00Z", "end_time": "2026-01-01T00:00:00Z"}):
        with pytest.raises(ValidationError):
            DiagnoseRequest(equipment_id="EQ-ROBOT-001", symptom="模拟现象", **extra)


def test_policy_table_name_cannot_be_sql(system):
    from app.security.policies import PolicyStore
    service, _ = system
    with pytest.raises(ValueError):
        PolicyStore(service.sessions, resource_kind="documents; DROP TABLE users")


def test_equipment_pagination_counts_only_authorized_rows(system):
    service, token = system
    assert service.list_equipment(token)["total"] == 0
    label(service, "equipment", "EQ-ROBOT-001", "B")
    label(service, "equipment", "EQ-ROBOT-002")
    label(service, "equipment", "EQ-ROBOT-003")
    first = service.list_equipment(token, limit=1)
    second = service.list_equipment(token, limit=1, offset=1)
    assert first["total"] == second["total"] == 2
    assert first["items"][0].equipment_id == "EQ-ROBOT-002"
    assert second["items"][0].equipment_id == "EQ-ROBOT-003"
    assert service.list_equipment(token, offset=2)["items"] == []


def test_equipment_revocation_during_list_prevents_response(system, monkeypatch):
    service, token = system
    label(service, "equipment", "EQ-ROBOT-001")
    store = service.stores["equipment"]
    original = store.list_policies
    calls = 0

    def changing_policies():
        nonlocal calls
        calls += 1
        if calls == 2:
            old = original()[0]
            store.save(old.model_copy(update={"status": "disabled", "policy_version": 2}),
                       expected_version=1, actor_id="test-admin")
        return original()

    monkeypatch.setattr(store, "list_policies", changing_policies)
    with pytest.raises(ResourceUnavailable):
        service.list_equipment(token)


def test_http_business_routes_authentication_and_limits(system):
    from fastapi.testclient import TestClient

    from app.api.server import create_app
    service, token = system
    app = create_app(service.sessions.path, service.path)
    client = TestClient(app)
    auth = {"Authorization": "Bearer " + token}
    base = "/api/v1/equipment/EQ-ROBOT-001"
    for suffix in ("", "/alarms", "/maintenance"):
        assert client.get(base + suffix).status_code == 401
        assert client.get(base + suffix, headers=auth).status_code == 404
    label(service, "equipment", "EQ-ROBOT-001")
    assert client.get(base, headers=auth).json()["model"] == "UR3e"
    assert client.get(base + "/alarms", headers=auth).json() == []
    assert client.get(base + "/alarms?limit=51", headers=auth).status_code == 422
    assert client.get(base + "/maintenance?limit=0", headers=auth).status_code == 422
    for suffix in ("/alarms", "/maintenance"):
        for params in ({"start_time": "2026-01-01T00:00:00"},
                       {"start_time": "2026-02-01T00:00:00Z", "end_time": "2026-01-01T00:00:00Z"},
                       {"start_time": "not-a-date"}):
            response = client.get(base + suffix, params=params, headers=auth)
            assert response.status_code == 422 and response.json()["code"] == "INPUT_ERROR"
        assert client.get(base + suffix, params={"end_time": "2020-01-01T00:00:00Z"},
                          headers=auth).json() == []
