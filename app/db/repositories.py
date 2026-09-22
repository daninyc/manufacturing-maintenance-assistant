"""三种固定、参数化、只读业务查询；不接受用户或模型提供的 SQL。"""
from pathlib import Path
from uuid import uuid4

from app.core.config import DATABASE_PATH
from app.db.session import DataAccessError, read_connection
from app.schemas.maintenance import (
    Alarm,
    Equipment,
    EquipmentLookup,
    MaintenanceRecord,
    RecordQuery,
)


class MaintenanceRepository:
    def __init__(self, path: Path = DATABASE_PATH, *, request_id: str | None = None):
        self.path = Path(path)
        self.request_id = request_id or str(uuid4())

    def _require_equipment(self, connection, equipment_id: str):
        row = connection.execute(
            "SELECT * FROM equipment WHERE equipment_id = ?", (equipment_id,)).fetchone()
        if row is None:
            raise DataAccessError("EQUIPMENT_NOT_FOUND", "设备编号不存在", self.request_id)
        return row

    def get_equipment(self, equipment_id: str) -> Equipment:
        request = EquipmentLookup(equipment_id=equipment_id)
        with read_connection(self.path, self.request_id) as connection:
            return Equipment.model_validate(dict(self._require_equipment(connection, request.equipment_id)))

    def list_recent_alarms(self, equipment_id: str, limit: int = 5,
                           severity: str | None = None) -> list[Alarm]:
        request = RecordQuery(equipment_id=equipment_id, limit=limit, severity=severity)
        with read_connection(self.path, self.request_id) as connection:
            self._require_equipment(connection, request.equipment_id)
            # SQL 结构固定，设备号/级别/limit 都通过 ? 绑定，不能成为 SQL 语法。
            rows = connection.execute(
                """SELECT * FROM alarms WHERE equipment_id = ?
                   AND (? IS NULL OR severity = ?)
                   ORDER BY occurred_at DESC, alarm_id DESC LIMIT ?""",
                (request.equipment_id, request.severity, request.severity, request.limit)).fetchall()
            return [Alarm.model_validate(dict(row)) for row in rows]

    def list_maintenance_history(self, equipment_id: str, limit: int = 5) -> list[MaintenanceRecord]:
        request = RecordQuery(equipment_id=equipment_id, limit=limit)
        with read_connection(self.path, self.request_id) as connection:
            self._require_equipment(connection, request.equipment_id)
            rows = connection.execute(
                """SELECT * FROM maintenance_records WHERE equipment_id = ?
                   ORDER BY maintained_at DESC, record_id DESC LIMIT ?""",
                (request.equipment_id, request.limit)).fetchall()
            # 已知设备无历史 → []；未知设备 → EQUIPMENT_NOT_FOUND，二者不可混同。
            return [MaintenanceRecord.model_validate(dict(row)) for row in rows]
