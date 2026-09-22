"""SQLite DDL：只有三张业务表；DTO 定义在 schemas/maintenance.py。"""

APPLICATION_ID = 0x4D4D4133
SCHEMA_VERSION = 1

# 每条单独 execute，避免 executescript 的隐式提交破坏整个种子事务。
SCHEMA = (
    """CREATE TABLE IF NOT EXISTS equipment (
        equipment_id TEXT PRIMARY KEY NOT NULL,
        name TEXT NOT NULL, model TEXT NOT NULL, equipment_type TEXT NOT NULL,
        production_line TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('active','offline','maintenance')),
        installation_date TEXT NOT NULL,
        source_type TEXT NOT NULL CHECK(source_type = 'simulation'))""",
    """CREATE TABLE IF NOT EXISTS alarms (
        alarm_id TEXT PRIMARY KEY NOT NULL,
        equipment_id TEXT NOT NULL REFERENCES equipment(equipment_id),
        code TEXT NOT NULL,
        severity TEXT NOT NULL CHECK(severity IN ('info','warning','critical')),
        message TEXT NOT NULL, occurred_at TEXT NOT NULL,
        acknowledged INTEGER NOT NULL CHECK(acknowledged IN (0,1)),
        resolved INTEGER NOT NULL CHECK(resolved IN (0,1)),
        document_id TEXT NOT NULL,
        source_type TEXT NOT NULL CHECK(source_type = 'simulation'))""",
    """CREATE TABLE IF NOT EXISTS maintenance_records (
        record_id TEXT PRIMARY KEY NOT NULL,
        equipment_id TEXT NOT NULL REFERENCES equipment(equipment_id),
        symptom TEXT NOT NULL, action TEXT NOT NULL,
        result TEXT NOT NULL CHECK(result IN ('resolved','unresolved','escalated')),
        maintained_at TEXT NOT NULL, document_id TEXT NOT NULL,
        source_type TEXT NOT NULL CHECK(source_type = 'simulation'))""",
    """CREATE INDEX IF NOT EXISTS idx_alarms_equipment_time
        ON alarms(equipment_id, occurred_at DESC, alarm_id DESC)""",
    """CREATE INDEX IF NOT EXISTS idx_maintenance_equipment_time
        ON maintenance_records(equipment_id, maintained_at DESC, record_id DESC)""",
)
