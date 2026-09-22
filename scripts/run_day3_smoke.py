"""本地 Day 3 验收；主库只读，写入/锁定/空历史实验均在独立临时库。"""
import argparse
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from app.core.config import DATABASE_PATH, PROJECT_ROOT
from app.db.seed import seed_database
from app.db.session import DataAccessError, read_connection
from app.services.data_service import query_data


def run(path: Path = DATABASE_PATH) -> dict:
    rows = []

    def record(name, passed, actual):
        rows.append({"case": name, "passed": bool(passed), "actual": actual})

    base = {"equipment_id": "EQ-ROBOT-001"}
    for operation, expected in [("equipment", "UR3e"), ("alarms", ["A-001-005", "A-001-004"]),
                                ("maintenance", ["M-001-003", "M-001-002"])]:
        result = query_data({**base, "operation": operation, "limit": 2}, path=path)
        data = result.get("data")
        if operation == "equipment":
            actual = data.get("model") if isinstance(data, dict) else None
        else:
            key = "alarm_id" if operation == "alarms" else "record_id"
            actual = [row[key] for row in data] if isinstance(data, list) else None
        record(operation, result["ok"] and actual == expected, result)

    result = query_data({**base, "operation": "alarms", "severity": "critical"}, path=path)
    record("severity", result["ok"] and [r["alarm_id"] for r in result.get("data", [])]
           == ["A-001-005", "A-001-003"], result)
    for operation in ("equipment", "alarms", "maintenance"):
        for name, equipment_id in [("unknown", "EQ-NOT-FOUND"), ("injection", "' OR 1=1 --")]:
            result = query_data({"operation": operation, "equipment_id": equipment_id}, path=path)
            record(f"{name}_{operation}", result.get("code") == "EQUIPMENT_NOT_FOUND", result)
    for value in (-1, 0, 51, "abc", True):
        result = query_data({**base, "operation": "alarms", "limit": value}, path=path)
        record(f"invalid_limit_{value}", result.get("code") == "INPUT_ERROR", result)
    result = query_data({**base, "operation": "alarms", "severity": "fatal"}, path=path)
    record("invalid_severity", result.get("code") == "INPUT_ERROR", result)

    try:
        with read_connection(path, "smoke-schema-" + uuid4().hex) as connection:
            counts = {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                      for table in ("equipment", "alarms", "maintenance_records")}
            foreign_keys_ok = not connection.execute("PRAGMA foreign_key_check").fetchall()
        record("main_counts_and_relations", counts == {"equipment": 3, "alarms": 15,
               "maintenance_records": 9} and foreign_keys_ok, counts)
    except DataAccessError as exc:
        record("main_counts_and_relations", False, {"code": exc.code, "request_id": exc.request_id})

    # 仅清理本脚本创建的临时目录；从不在主库执行故障注入或 DELETE/UPDATE。
    with TemporaryDirectory(prefix="day3-test-temp-smoke-", dir=PROJECT_ROOT / "data") as directory:
        scratch = Path(directory)
        test_db = scratch / "test.sqlite3"
        first, second = seed_database(test_db), seed_database(test_db)
        record("repeat_seed", first["after"] == second["before"] == second["after"], [first, second])
        missing = scratch / "missing.sqlite3"
        result = query_data({**base, "operation": "equipment"}, path=missing)
        record("missing_database", result.get("code") == "DATABASE_NOT_FOUND" and not missing.exists(), result)
        empty = scratch / "empty.sqlite3"
        seed_database(empty, seed_path=PROJECT_ROOT / "data/seed/empty_history.json")
        result = query_data({"equipment_id": "EQ-TEST-EMPTY", "operation": "maintenance"}, path=empty)
        record("known_equipment_empty_history", result["ok"] and result["data"] == [], result)
        with closing(sqlite3.connect(test_db, isolation_level=None)) as writer:
            writer.execute("BEGIN EXCLUSIVE")
            try:
                result = query_data({**base, "operation": "equipment"}, path=test_db)
            finally:
                writer.rollback()
        record("locked_database", result.get("code") == "DATABASE_BUSY", result)
        denied = False
        try:
            with read_connection(test_db, "smoke-readonly-" + uuid4().hex) as connection:
                connection.execute("UPDATE equipment SET name='should-not-write'")
        except DataAccessError as exc:
            denied = exc.code == "DATABASE_ERROR"
        result = query_data({**base, "operation": "equipment"}, path=test_db)
        record("read_only_write_denied", denied and result["ok"]
               and result["data"]["name"] != "should-not-write", {"write_denied": denied})

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    output = PROJECT_ROOT / f"docs/evidence/day3/smoke-{run_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {"run_id": run_id, "source_type": "self_authored_simulation",
              "passed": sum(row["passed"] for row in rows), "total": len(rows), "cases": rows}
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"passed={report['passed']}/{report['total']}")
    print(output)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="验证 Day 3 固定查询与错误边界，不调用模型")
    parser.add_argument("--db", type=Path, default=DATABASE_PATH)
    args = parser.parse_args()
    report = run(args.db)
    if report["passed"] != report["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
