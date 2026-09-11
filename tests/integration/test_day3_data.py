import json
import sqlite3
from contextlib import closing

import pytest
from pydantic import ValidationError

from app.core.config import PROJECT_ROOT
from app.db.models import APPLICATION_ID
from app.db.repositories import MaintenanceRepository
from app.db.seed import load_seed, seed_database
from app.db.session import DataAccessError, read_connection
from app.schemas.maintenance import DataQuery, SeedDataset
from app.services.data_service import query_data


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "maintenance.sqlite3"
    seed_database(path)
    return path


def test_schema_foreign_keys_indexes_and_counts(database):
    with read_connection(database, "schema-test") as connection:
        tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert tables == {"equipment", "alarms", "maintenance_records"}
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
        assert connection.execute("PRAGMA application_id").fetchone()[0] == APPLICATION_ID
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        for table in ("alarms", "maintenance_records"):
            assert connection.execute(f"PRAGMA foreign_key_list({table})").fetchone()[2] == "equipment"
        for equipment_id in ("EQ-ROBOT-001", "EQ-ROBOT-002", "EQ-ROBOT-003"):
            assert connection.execute("SELECT COUNT(*) FROM alarms WHERE equipment_id=?",
                                      (equipment_id,)).fetchone()[0] == 5
            assert connection.execute("SELECT COUNT(*) FROM maintenance_records WHERE equipment_id=?",
                                      (equipment_id,)).fetchone()[0] == 3
        plan = connection.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM alarms WHERE equipment_id=? "
            "ORDER BY occurred_at DESC, alarm_id DESC LIMIT ?", ("EQ-ROBOT-001", 2)).fetchall()
        assert any("idx_alarms_equipment_time" in row[3] for row in plan)


def test_seed_idempotent_and_preserves_unrelated_records(database):
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("INSERT INTO equipment SELECT 'EXTRA', name, model, equipment_type, "
                           "production_line, status, installation_date, source_type "
                           "FROM equipment WHERE equipment_id='EQ-ROBOT-001'")
    report = seed_database(database)
    assert report["before"] == report["after"] == {
        "equipment": 4, "alarms": 15, "maintenance_records": 9}


def test_equipment_dto_and_records_order(database):
    repository = MaintenanceRepository(database)
    equipment = repository.get_equipment("EQ-ROBOT-001")
    assert equipment.model == "UR3e" and equipment.source_type == "simulation"
    alarms = repository.list_recent_alarms("EQ-ROBOT-001", 2)
    assert [row.alarm_id for row in alarms] == ["A-001-005", "A-001-004"]
    assert alarms[0].code == "SIM-UNKNOWN-999" and not alarms[0].resolved
    records = repository.list_maintenance_history("EQ-ROBOT-001", 2)
    assert [row.record_id for row in records] == ["M-001-003", "M-001-002"]
    assert records[0].result == "unresolved"
    assert not hasattr(repository, "execute_sql")


def test_severity_filter_and_same_time_tie_break(database):
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("UPDATE alarms SET occurred_at='2026-09-07T08:00:00.000000Z' WHERE alarm_id='A-001-003'")
    rows = MaintenanceRepository(database).list_recent_alarms("EQ-ROBOT-001", 50, "critical")
    assert [row.alarm_id for row in rows] == ["A-001-005", "A-001-003"]
    assert all(row.severity == "critical" for row in rows)


@pytest.mark.parametrize("operation", ["equipment", "alarms", "maintenance"])
@pytest.mark.parametrize("equipment_id", ["EQ-NOT-FOUND", "' OR 1=1 --"])
def test_unknown_and_injection_are_not_found(database, operation, equipment_id):
    result = query_data({"operation": operation, "equipment_id": equipment_id}, path=database)
    assert not result["ok"] and result["code"] == "EQUIPMENT_NOT_FOUND"
    assert result["request_id"]
    assert "data" not in result


@pytest.mark.parametrize("limit", [-1, 0, 51, "abc", "2", 2.5, True, None])
def test_limit_schema_and_repository_boundary(database, limit):
    with pytest.raises(ValidationError):
        DataQuery(operation="alarms", equipment_id="EQ-ROBOT-001", limit=limit)
    with pytest.raises(ValidationError):
        MaintenanceRepository(database).list_recent_alarms("EQ-ROBOT-001", limit)
    assert query_data({"operation": "maintenance", "equipment_id": "EQ-ROBOT-001", "limit": limit},
                      path=database)["code"] == "INPUT_ERROR"


@pytest.mark.parametrize("changes", [{"equipment_id": "  "}, {"severity": "fatal"},
                                     {"operation": "maintenance", "severity": "critical"},
                                     {"sql": "DROP TABLE equipment"}, {"operation": "execute_sql"}])
def test_invalid_inputs_before_database(tmp_path, changes):
    payload = {"operation": "alarms", "equipment_id": "EQ-ROBOT-001", **changes}
    assert query_data(payload, path=tmp_path / "absent.sqlite3")["code"] == "INPUT_ERROR"


def test_empty_history_is_success_not_unknown(tmp_path):
    path = tmp_path / "empty.sqlite3"
    seed_database(path, seed_path=PROJECT_ROOT / "data/seed/empty_history.json")
    response = query_data({"operation": "maintenance", "equipment_id": "EQ-TEST-EMPTY"}, path=path)
    assert response["ok"] and response["data"] == []


def test_missing_database_does_not_create_file(tmp_path, caplog):
    path = tmp_path / "missing.sqlite3"
    result = query_data({"operation": "equipment", "equipment_id": "EQ-ROBOT-001"}, path=path)
    assert result["code"] == "DATABASE_NOT_FOUND" and not path.exists()
    assert result["request_id"] in caplog.text


def test_locked_database_has_request_id(database, caplog):
    with closing(sqlite3.connect(database, isolation_level=None)) as writer:
        writer.execute("BEGIN EXCLUSIVE")
        try:
            result = query_data({"operation": "equipment", "equipment_id": "EQ-ROBOT-001"}, path=database)
        finally:
            writer.rollback()
    assert result["code"] == "DATABASE_BUSY"
    assert result["request_id"] in caplog.text
    assert query_data({"operation": "equipment", "equipment_id": "EQ-ROBOT-001"}, path=database)["ok"]


@pytest.mark.parametrize("statement", ["DELETE FROM equipment", "UPDATE equipment SET name='bad'"])
def test_read_only_connection_rejects_writes(database, statement):
    with (pytest.raises(DataAccessError, match="数据库读取或结构异常"),
          read_connection(database, "read-only-test") as connection):
        connection.execute(statement)
    assert MaintenanceRepository(database).get_equipment("EQ-ROBOT-001").name != "bad"


def test_foreign_key_write_is_rejected(database):
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError), connection:
            connection.execute("UPDATE alarms SET equipment_id='DOES-NOT-EXIST'")


def test_failed_seed_transaction_rolls_back(database):
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("UPDATE equipment SET name='preserve-this' WHERE equipment_id='EQ-ROBOT-001'")
        connection.execute("CREATE TRIGGER fail_seed BEFORE UPDATE ON alarms "
                           "BEGIN SELECT RAISE(ABORT,'test failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        seed_database(database)
    assert MaintenanceRepository(database).get_equipment("EQ-ROBOT-001").name == "preserve-this"


def test_unrelated_database_is_not_overwritten(tmp_path):
    path = tmp_path / "other.sqlite3"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE personal(note TEXT)")
        connection.execute("INSERT INTO personal VALUES ('keep')")
    with pytest.raises(ValueError, match="拒绝修改"):
        seed_database(path)
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("SELECT note FROM personal").fetchone()[0] == "keep"
    result = query_data({"operation": "equipment", "equipment_id": "EQ-ROBOT-001"}, path=path)
    assert result["code"] == "DATABASE_SCHEMA_ERROR"


def test_corrupt_database_and_invalid_stored_dto(tmp_path, database):
    path = tmp_path / "corrupt.sqlite3"
    path.write_bytes(b"not sqlite")
    request = {"operation": "equipment", "equipment_id": "EQ-ROBOT-001"}
    assert query_data(request, path=path)["code"] == "DATABASE_ERROR"
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("UPDATE equipment SET installation_date='not-a-date'")
    assert query_data(request, path=database)["code"] == "DATA_INTEGRITY_ERROR"


def test_seed_validation_and_document_links(tmp_path):
    original = load_seed(PROJECT_ROOT / "data/seed/maintenance.json")
    content = original.model_dump(mode="json")
    content["alarms"][0]["document_id"] = "FAKE-DOCUMENT"
    path = tmp_path / "seed.json"
    path.write_text(json.dumps(content), encoding="utf-8")
    with pytest.raises(ValueError, match="文档"):
        seed_database(tmp_path / "never-created.sqlite3", seed_path=path)
    assert not (tmp_path / "never-created.sqlite3").exists()
    for field, value in [("equipment_id", "UNKNOWN"), ("occurred_at", "2020-01-01T00:00:00Z"),
                         ("occurred_at", "2026-09-03T08:00:00")]:
        content = original.model_dump(mode="json")
        content["alarms"][0][field] = value
        with pytest.raises(ValidationError):
            SeedDataset.model_validate(content)


def test_fractional_time_sorting_uses_fixed_utc_format(tmp_path):
    content = load_seed(PROJECT_ROOT / "data/seed/maintenance.json").model_dump(mode="json")
    content["alarms"][2]["occurred_at"] = "2026-09-07T08:00:00Z"
    content["alarms"][4]["occurred_at"] = "2026-09-07T08:00:00.100Z"
    fixture = tmp_path / "fractional.json"
    fixture.write_text(json.dumps(content), encoding="utf-8")
    path = tmp_path / "fractional.sqlite3"
    seed_database(path, seed_path=fixture)
    rows = MaintenanceRepository(path).list_recent_alarms("EQ-ROBOT-001", 2, "critical")
    assert [row.alarm_id for row in rows] == ["A-001-005", "A-001-003"]
