"""python -m scripts.seed_db：仅离线初始化/更新模拟数据，不清表。"""
import argparse
import json
import sqlite3
from pathlib import Path
from uuid import uuid4

from app.core.config import DATABASE_PATH, PROJECT_ROOT
from app.db.seed import seed_database
from app.db.session import database_error


def main() -> None:
    parser = argparse.ArgumentParser(description="初始化 Day 3 模拟数据库（同主键更新，不清表）")
    parser.add_argument("--db", type=Path, default=DATABASE_PATH)
    parser.add_argument("--fixture", choices=["standard", "empty-history"], default="standard")
    args = parser.parse_args()
    if args.fixture == "empty-history" and args.db.resolve() == DATABASE_PATH.resolve():
        parser.error("空历史样例必须通过 --db 指定独立数据库，不能混入主数据")
    request_id = str(uuid4())
    seed_path = PROJECT_ROOT / "data/seed" / (
        "maintenance.json" if args.fixture == "standard" else "empty_history.json")
    try:
        report = {"ok": True, "request_id": request_id, **seed_database(args.db, seed_path=seed_path)}
    except sqlite3.Error as exc:
        error = database_error(exc, request_id)
        report = {"ok": False, "request_id": request_id, "code": error.code, "message": str(error)}
    except (OSError, ValueError):
        report = {"ok": False, "request_id": request_id, "code": "SEED_ERROR",
                  "message": "种子数据/数据库身份校验失败，或文件不可访问；未清除现有数据"}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
