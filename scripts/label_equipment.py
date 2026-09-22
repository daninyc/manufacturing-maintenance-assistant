"""Explicit administrator-approved initial labels; existing labels are never replaced."""
import argparse
import time
from getpass import getpass
from pathlib import Path
from uuid import uuid4

from app.auth.sessions import AuthenticationError, SessionStore
from app.core.config import DATABASE_PATH, PROJECT_ROOT
from app.db.session import read_connection
from app.schemas.maintenance import EquipmentLookup
from app.security.authorization import ResourcePolicy, can_manage
from app.security.policies import PolicyConflict


def label_equipment(sessions: SessionStore, token: str, business_path: Path,
                    equipment_id: str, *, department: str, classification: int) -> dict:
    actor = sessions.authenticate(token)
    if not can_manage(actor):
        raise PermissionError("Administrator required")
    equipment_id = EquipmentLookup(equipment_id=equipment_id).equipment_id
    base = ResourcePolicy(resource_id=equipment_id, department_id=department,
                          classification=classification, visibility="department",
                          status="active", policy_version=1,
                          content_version="simulation-v1", external_processing_allowed=False)
    with read_connection(business_path, str(uuid4())) as business:
        equipment = business.execute("SELECT equipment_id FROM equipment WHERE equipment_id=?",
                                     (equipment_id,)).fetchone()
        if equipment is None:
            raise ValueError("Unknown equipment")
        resources = {"equipment": [equipment_id]}
        resources["alarm"] = [r[0] for r in business.execute(
            "SELECT alarm_id FROM alarms WHERE equipment_id=? ORDER BY alarm_id", (equipment_id,))]
        resources["maintenance"] = [r[0] for r in business.execute(
            "SELECT record_id FROM maintenance_records WHERE equipment_id=? ORDER BY record_id",
            (equipment_id,))]
        with sessions.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            # Holding the access write lock prevents concurrent account changes
            # between this check and committing labels and audit events.
            if sessions.authenticate(token) != actor:
                raise AuthenticationError()
            for kind, ids in resources.items():
                table = kind + "_policies"  # only the three fixed keys above
                for resource_id in ids:
                    if db.execute(f"SELECT 1 FROM {table} WHERE resource_id=?",
                                  (resource_id,)).fetchone():
                        raise PolicyConflict("Existing labels require explicit versioned update")
                    policy = base.model_copy(update={"resource_id": resource_id})
                    db.execute(f"INSERT INTO {table} VALUES (?,?,?)",
                               (resource_id, 1, policy.model_dump_json()))
                    db.execute("INSERT INTO audit_events VALUES (NULL,?,?,?,?,?)",
                               (actor.user_id, kind + ".policy.import", resource_id, 1, time.time()))
    # Document policies remain untouched: labels cannot authorize their contents.
    return {kind: len(ids) for kind, ids in resources.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=PROJECT_ROOT / "data/access.sqlite3")
    parser.add_argument("--business-database", type=Path, default=DATABASE_PATH)
    parser.add_argument("--username", required=True)
    parser.add_argument("--equipment-id", required=True)
    parser.add_argument("--department", required=True)
    parser.add_argument("--classification", type=int, choices=[0, 1, 2], required=True)
    args = parser.parse_args()
    sessions = SessionStore(args.database)
    token = sessions.login(args.username, getpass("Administrator password: "))
    try:
        print(label_equipment(sessions, token, args.business_database, args.equipment_id,
                              department=args.department, classification=args.classification))
    finally:
        try:
            sessions.logout(token)
        except AuthenticationError:
            pass


if __name__ == "__main__":
    main()
