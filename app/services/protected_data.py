"""Read-only business queries with authorization before ordering and pagination."""
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.auth.sessions import AuthenticationError, SessionStore
from app.db.session import read_connection
from app.schemas.diagnosis import TimeRange
from app.schemas.maintenance import Alarm, Equipment, MaintenanceRecord, RecordQuery
from app.security.authorization import can_read
from app.security.policies import PolicyStore


class ResourceUnavailable(RuntimeError):
    """Same external error for missing and forbidden resources."""


class ProtectedMaintenance:
    def __init__(self, path: Path, sessions: SessionStore):
        self.path = path
        self.sessions = sessions
        self.stores = {kind: PolicyStore(sessions, resource_kind=kind)
                       for kind in ("document", "equipment", "alarm", "maintenance")}

    def list_equipment(self, token: str, *, limit: int = 20, offset: int = 0):
        if (type(limit) is not int or not 1 <= limit <= 50
                or type(offset) is not int or not 0 <= offset <= 100000):
            raise ValueError("Invalid pagination")
        subject = self.sessions.authenticate(token)
        before = self.stores["equipment"].list_policies()
        allowed = {p.resource_id for p in before if can_read(subject, p)}
        with read_connection(self.path, str(uuid4())) as db:
            db.create_function("authorized_equipment", 1, lambda key: key in allowed)
            total = db.execute("SELECT COUNT(*) FROM equipment "
                               "WHERE authorized_equipment(equipment_id)").fetchone()[0]
            rows = db.execute("SELECT * FROM equipment WHERE authorized_equipment(equipment_id) "
                              "ORDER BY equipment_id LIMIT ? OFFSET ?", (limit, offset)).fetchall()
            items = [Equipment.model_validate(dict(row)) for row in rows]
        if self.sessions.authenticate(token) != subject:
            raise AuthenticationError()
        if self.stores["equipment"].list_policies() != before:
            raise ResourceUnavailable()
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    def query(self, token: str, operation: str, equipment_id: str,
              *, limit: int = 5, severity: str | None = None,
              start_time: datetime | None = None, end_time: datetime | None = None):
        if operation not in {"equipment", "alarms", "maintenance"}:
            raise ValueError("Unknown operation")
        request = RecordQuery(equipment_id=equipment_id, limit=limit, severity=severity)
        period = TimeRange(start_time=start_time, end_time=end_time)
        start, end = [value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                      if value is not None else None
                      for value in (period.start_time, period.end_time)]
        if severity is not None and operation != "alarms":
            raise ValueError("Severity only applies to alarms")
        subject = self.sessions.authenticate(token)
        equipment_policy = self.stores["equipment"].get_many([request.equipment_id])
        if not can_read(subject, equipment_policy.get(request.equipment_id)):
            raise ResourceUnavailable()
        snapshots = {"equipment": equipment_policy}
        kind = "alarm" if operation == "alarms" else "maintenance"
        if operation != "equipment":
            # ponytail: snapshots fit the demo; use SQL joins for large catalogs.
            for key in ("document", kind):
                snapshots[key] = {p.resource_id: p for p in self.stores[key].list_policies()}

        def allowed_record(record_id, document_id):
            # Explicit record labels are mandatory, including inherited labels
            # materialized during import. Missing labels never grant access.
            return (can_read(subject, snapshots["document"].get(document_id))
                    and can_read(subject, snapshots[kind].get(record_id)))

        with read_connection(self.path, str(uuid4())) as db:
            equipment = db.execute("SELECT * FROM equipment WHERE equipment_id=?",
                                   (request.equipment_id,)).fetchone()
            if equipment is None:
                raise ResourceUnavailable()
            if operation == "equipment":
                result = Equipment.model_validate(dict(equipment))
            else:
                # This local predicate runs in WHERE, before LIMIT; no writes.
                db.create_function("authorized_record", 2, allowed_record)
                if operation == "alarms":
                    rows = db.execute("""SELECT * FROM alarms WHERE equipment_id=?
                        AND authorized_record(alarm_id, document_id)
                        AND (? IS NULL OR severity=?)
                        AND (? IS NULL OR occurred_at>=?)
                        AND (? IS NULL OR occurred_at<=?)
                        ORDER BY occurred_at DESC, alarm_id DESC LIMIT ?""",
                        (request.equipment_id, severity, severity,
                         start, start, end, end, request.limit)).fetchall()
                    result = [Alarm.model_validate(dict(row)) for row in rows]
                else:
                    rows = db.execute("""SELECT * FROM maintenance_records WHERE equipment_id=?
                        AND authorized_record(record_id, document_id)
                        AND (? IS NULL OR maintained_at>=?)
                        AND (? IS NULL OR maintained_at<=?)
                        ORDER BY maintained_at DESC, record_id DESC LIMIT ?""",
                        (request.equipment_id, start, start, end, end, request.limit)).fetchall()
                    result = [MaintenanceRecord.model_validate(dict(row)) for row in rows]

        if self.sessions.authenticate(token) != subject:
            raise AuthenticationError()
        for key, before in snapshots.items():
            current = (self.stores[key].get_many([request.equipment_id])
                       if key == "equipment" else
                       {p.resource_id: p for p in self.stores[key].list_policies()})
            if current != before:
                raise ResourceUnavailable()
        return result
