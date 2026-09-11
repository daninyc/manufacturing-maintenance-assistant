"""Day 3 固定业务查询 CLI；没有 --sql 或任意工具执行参数。"""
import argparse
import json
from pathlib import Path

from app.core.config import DATABASE_PATH
from app.services.data_service import query_data


def main() -> None:
    parser = argparse.ArgumentParser(description="只读查询模拟设备、报警和维修记录")
    parser.add_argument("operation", choices=["equipment", "alarms", "maintenance"])
    parser.add_argument("--equipment-id", required=True)
    parser.add_argument("--limit", default="5")
    parser.add_argument("--severity")
    parser.add_argument("--db", type=Path, default=DATABASE_PATH)
    args = parser.parse_args()
    # 转换失败保留字符串，让统一 schema 返回带 request_id 的 INPUT_ERROR。
    try:
        limit = int(args.limit)
    except ValueError:
        limit = args.limit
    result = query_data({"operation": args.operation, "equipment_id": args.equipment_id,
                         "limit": limit, "severity": args.severity}, path=args.db)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
