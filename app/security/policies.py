"""权威资源策略：按资源类型存储标签，以期望版本比较更新，并在同一事务记审计。

版本冲突拒绝覆盖；管理列表不返回正文、服务器路径或密码凭证。
"""
import time

from app.auth.sessions import SessionStore
from app.security.authorization import ResourcePolicy


class PolicyConflict(ValueError):
    pass


class PolicyStore:
    def __init__(self, sessions: SessionStore, *, resource_kind: str = "document"):
        if resource_kind not in {"document", "equipment", "alarm", "maintenance"}:
            raise ValueError("Unknown resource kind")
        self.sessions = sessions
        self.resource_kind = resource_kind
        self.table = "documents" if resource_kind == "document" else resource_kind + "_policies"

    def initialize(self):
        self.sessions.initialize()
        with self.sessions.connect() as db:
            db.execute(f"""CREATE TABLE IF NOT EXISTS {self.table} (
                resource_id TEXT PRIMARY KEY NOT NULL, policy_version INTEGER NOT NULL,
                policy_json TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS audit_events (
                event_id INTEGER PRIMARY KEY, actor_id TEXT NOT NULL,
                action TEXT NOT NULL, resource_id TEXT NOT NULL,
                version INTEGER NOT NULL, created_at REAL NOT NULL)""")

    def get_many(self, ids: list[str]) -> dict[str, ResourcePolicy]:
        result = {}
        with self.sessions.connect() as db:
            for start in range(0, len(ids), 200):
                batch = ids[start:start + 200]
                placeholders = ",".join("?" for _ in batch)
                for row in db.execute(
                    f"SELECT policy_json FROM {self.table} WHERE resource_id IN ({placeholders})",
                    batch,
                ):
                    policy = ResourcePolicy.model_validate_json(row["policy_json"])
                    result[policy.resource_id] = policy
        return result

    def save(self, policy: ResourcePolicy, *, expected_version: int, actor_id: str,
             actor_token: str | None = None):
        """Compare-and-swap and audit in one write transaction."""
        if type(expected_version) is not int or expected_version < 0:
            raise ValueError("Invalid expected version")
        if policy.policy_version != expected_version + 1:
            raise PolicyConflict("Policy version must advance")
        with self.sessions.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if actor_token is not None:
                self.sessions.require_current_admin(db, actor_token, actor_id)
            if expected_version == 0:
                exists = db.execute(f"SELECT 1 FROM {self.table} WHERE resource_id=?",
                                    (policy.resource_id,)).fetchone()
                if exists:
                    raise PolicyConflict("Policy changed")
                db.execute(f"INSERT INTO {self.table} VALUES (?,?,?)",
                           (policy.resource_id, policy.policy_version, policy.model_dump_json()))
            else:
                result = db.execute(
                    f"""UPDATE {self.table} SET policy_version=?, policy_json=?
                       WHERE resource_id=? AND policy_version=?""",
                    (policy.policy_version, policy.model_dump_json(),
                     policy.resource_id, expected_version))
                if result.rowcount != 1:
                    raise PolicyConflict("Policy changed")
            db.execute("INSERT INTO audit_events VALUES (NULL,?,?,?,?,?)",
                       (actor_id, f"{self.resource_kind}.policy.update", policy.resource_id,
                        policy.policy_version, time.time()))

    def list_policies(self) -> list[ResourcePolicy]:
        with self.sessions.connect() as db:
            return [ResourcePolicy.model_validate_json(row["policy_json"])
                    for row in db.execute(f"SELECT policy_json FROM {self.table} ORDER BY resource_id")]

    def management_page(self, *, limit: int, offset: int) -> dict:
        """Metadata only; caller must authorize management and recheck before response."""
        if type(limit) is not int or type(offset) is not int or not 1 <= limit <= 50 or not 0 <= offset <= 100000:
            raise ValueError("Invalid pagination")
        with self.sessions.connect() as db:
            db.execute("BEGIN")
            total = db.execute(f"SELECT COUNT(*) FROM {self.table}").fetchone()[0]
            items = [ResourcePolicy.model_validate_json(row["policy_json"])
                     for row in db.execute(
                         f"SELECT policy_json FROM {self.table} ORDER BY resource_id LIMIT ? OFFSET ?",
                         (limit, offset))]
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    def audit(self, actor_id: str, action: str, resource_id: str, version: int):
        with self.sessions.connect() as db:
            db.execute("INSERT INTO audit_events VALUES (NULL,?,?,?,?,?)",
                       (actor_id, action, resource_id, version, time.time()))

    def audit_events(self):
        with self.sessions.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM audit_events ORDER BY event_id")]
