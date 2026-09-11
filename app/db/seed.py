"""离线写入入口：先校验整包数据，再在单事务中建表和 upsert。"""
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from app.core.config import DATABASE_PATH, PROJECT_ROOT
from app.db.models import APPLICATION_ID, SCHEMA, SCHEMA_VERSION
from app.schemas.maintenance import SeedDataset

TABLES = ("equipment", "alarms", "maintenance_records")


def load_seed(path: Path) -> SeedDataset:
    dataset = SeedDataset.model_validate_json(path.read_text(encoding="utf-8"))
    manifest = json.loads((PROJECT_ROOT / "data/raw_docs/manifest.json").read_text(encoding="utf-8"))
    document_ids = {row["document_id"] for row in manifest}
    for row in [*dataset.alarms, *dataset.maintenance_records]:
        if row.document_id not in document_ids:
            raise ValueError("种子记录引用了 manifest 中不存在的文档")
    return dataset


def seed_database(path: Path = DATABASE_PATH, *, seed_path: Path | None = None) -> dict:
    dataset = load_seed(seed_path or PROJECT_ROOT / "data/seed/maintenance.json")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=1.0, isolation_level=None)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        try:
            identity = connection.execute("PRAGMA application_id").fetchone()[0]
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            existing = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if ((identity not in (0, APPLICATION_ID)) or (existing and identity != APPLICATION_ID)
                    or version not in (0, SCHEMA_VERSION)):
                raise ValueError("拒绝修改来源不明或版本不支持的数据库")
            for statement in SCHEMA:
                connection.execute(statement)
            before = {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                      for table in TABLES}
            # 表名与列名只来自程序常量和 Pydantic 模型，值全部绑定；不是通用 SQL 接口。
            for table, key in zip(TABLES, ("equipment_id", "alarm_id", "record_id"), strict=True):
                for row in getattr(dataset, table):
                    values = row.model_dump(mode="json")
                    # 固定 UTC 与微秒宽度，确保 TEXT 时间排序和真实时间先后一致。
                    for time_field in ("occurred_at", "maintained_at"):
                        if time_field in values:
                            values[time_field] = getattr(row, time_field).isoformat(
                                timespec="microseconds").replace("+00:00", "Z")
                    columns = list(values)
                    updates = ", ".join(f"{name}=excluded.{name}" for name in columns if name != key)
                    connection.execute(
                        f"INSERT INTO {table} ({', '.join(columns)}) "
                        f"VALUES ({', '.join('?' for _ in columns)}) "
                        f"ON CONFLICT({key}) DO UPDATE SET {updates}", tuple(values.values()))
            connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            after = {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                     for table in TABLES}
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {"source_type": dataset.source_type, "version": dataset.version,
            "before": before, "after": after}
