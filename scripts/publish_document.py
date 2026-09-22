"""Publish a local PDF/TXT with explicit access labels and interactive credentials."""
import argparse
from getpass import getpass
from pathlib import Path

from app.auth.sessions import SessionStore
from app.core.config import PROJECT_ROOT
from app.ingestion.publication import publish_document
from app.retrieval.vector_store import LocalChromaStore
from app.security.authorization import ResourcePolicy
from app.security.policies import PolicyStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--department", required=True)
    parser.add_argument("--classification", required=True, type=int, choices=[0, 1, 2])
    parser.add_argument("--visibility", choices=["department", "organization"], default="department")
    parser.add_argument("--allow-external", action="store_true")
    parser.add_argument("--equipment-id", default="")
    parser.add_argument("--expected-version", required=True, type=int)
    parser.add_argument("--username", default="admin")
    parser.add_argument("--database", type=Path, default=PROJECT_ROOT / "data/access.sqlite3")
    args = parser.parse_args()
    sessions = SessionStore(args.database)
    policies = PolicyStore(sessions)
    token = sessions.login(args.username, getpass("Administrator password: "))
    try:
        store = LocalChromaStore(PROJECT_ROOT / "data/chroma", "authorized_v1", semantic=True)
        policy = ResourcePolicy(resource_id=args.document_id, department_id=args.department,
                                visibility=args.visibility, classification=args.classification,
                                status="draft", policy_version=args.expected_version + 1,
                                content_version="pending",
                                external_processing_allowed=args.allow_external)
        active = publish_document(args.file, policy, store, policies, sessions, token,
                                  expected_version=args.expected_version,
                                  equipment_id=args.equipment_id)
        print(f"Published policy_version={active.policy_version}, status={active.status}")
    finally:
        try:
            sessions.logout(token)
        except ValueError:
            pass  # Already revoked/expired by an administrator.


if __name__ == "__main__":
    main()

