"""Explicit additive upgrade for an existing access database; never imports labels."""
import argparse
import sqlite3
from pathlib import Path
from uuid import uuid4

from app.auth.sessions import SessionStore
from app.core.config import PROJECT_ROOT


def upgrade_access(path: Path) -> Path:
    sessions = SessionStore(path)
    # Validate application identity before creating any backup or modifying data.
    with sessions.connect() as source:
        backup = path.with_name(path.name + ".before-resource-policies-" + uuid4().hex + ".bak")
        # Backup contains password hashes and sessions: keep it server-side and
        # inherit the protected access-directory permissions, never publish it.
        with backup.open("xb"):
            pass
        destination = sqlite3.connect(backup)
        try:
            source.backup(destination)
        finally:
            destination.close()
    with sessions.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        for table in ("equipment_policies", "alarm_policies", "maintenance_policies"):
            db.execute(f"CREATE TABLE IF NOT EXISTS {table} ("
                       "resource_id TEXT PRIMARY KEY NOT NULL, policy_version INTEGER NOT NULL, "
                       "policy_json TEXT NOT NULL)")
        # This is an additive schema extension of access v1, not a data relabel.
        # No active policy is synthesized, and no existing session is changed.
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=PROJECT_ROOT / "data/access.sqlite3")
    args = parser.parse_args()
    backup = upgrade_access(args.database)
    print(f"Resource policy tables ready. Protected backup: {backup}")


if __name__ == "__main__":
    main()
