"""Initialize a separate access database and create an administrator interactively."""
import argparse
from getpass import getpass
from pathlib import Path

from app.auth.sessions import SessionStore
from app.core.config import PROJECT_ROOT
from app.security.policies import PolicyStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=PROJECT_ROOT / "data/access.sqlite3")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--department", default="PLATFORM")
    args = parser.parse_args()
    password = getpass("Administrator password (12+ characters): ")
    if password != getpass("Repeat password: "):
        raise SystemExit("Passwords differ")
    sessions = SessionStore(args.database)
    for kind in ("document", "equipment", "alarm", "maintenance"):
        PolicyStore(sessions, resource_kind=kind).initialize()
    person = sessions.create_user(args.username, password, role="admin",
                                  department_id=args.department, clearance=2)
    print(f"Administrator created: {person.user_id}")


if __name__ == "__main__":
    main()
