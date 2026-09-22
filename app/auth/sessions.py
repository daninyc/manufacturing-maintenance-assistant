"""身份与会话：独立权限库保存密码散列和令牌摘要，业务库仍保持只读。

改权限、禁用和改密码使旧会话失效；管理写事务内复核操作者权限。
"""
import hashlib
import hmac
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from app.security.authorization import UserContext

APPLICATION_ID = 0x4D4D4155
VERSION = 1
SESSION_SECONDS = 3600


class AuthenticationError(ValueError):
    def __init__(self):
        super().__init__("Invalid or expired credentials")


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _password_hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32)


def _validate_password(password: str):
    if not isinstance(password, str) or not 12 <= len(password) <= 1024:
        raise ValueError("Password must contain 12 to 1024 characters")


class SessionStore:
    """Only authenticated server code may call the administrative mutation methods."""

    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        # Never silently create a missing access-control database during a request.
        connection = sqlite3.connect(self.path.resolve().as_uri() + "?mode=rw",
                                     uri=True, timeout=2)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            identity = connection.execute("PRAGMA application_id").fetchone()[0]
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if identity != APPLICATION_ID or version != VERSION:
                raise RuntimeError("Access database identity/version mismatch")
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Existing files must already belong to this application. No takeover.
        if self.path.exists():
            with self.connect():
                return
        with sqlite3.connect(self.path) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
            connection.execute(f"PRAGMA user_version={VERSION}")
            connection.execute("""CREATE TABLE users (
                user_id TEXT PRIMARY KEY NOT NULL,
                username TEXT UNIQUE NOT NULL,
                password_salt BLOB NOT NULL, password_hash BLOB NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('employee','engineer','admin')),
                department_id TEXT NOT NULL,
                clearance INTEGER NOT NULL CHECK(clearance BETWEEN 0 AND 2),
                active INTEGER NOT NULL CHECK(active IN (0,1)),
                authz_version INTEGER NOT NULL CHECK(authz_version >= 1))""")
            connection.execute("""CREATE TABLE sessions (
                token_hash TEXT PRIMARY KEY NOT NULL,
                user_id TEXT NOT NULL REFERENCES users(user_id),
                expires_at REAL NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0 CHECK(revoked IN (0,1)))""")
            connection.execute("CREATE INDEX sessions_user ON sessions(user_id)")

    def create_user(self, username: str, password: str, *, role: str,
                    department_id: str, clearance: int,
                    actor_id: str | None = None, actor_token: str | None = None) -> UserContext:
        _validate_password(password)
        if not isinstance(username, str) or not username.strip() or len(username) > 64:
            raise ValueError("Invalid username")
        subject = UserContext(user_id=secrets.token_hex(16), role=role,
                              department_id=department_id, clearance=clearance,
                              active=True, authz_version=1)
        salt = secrets.token_bytes(16)
        hashed = _password_hash(password, salt)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if actor_token is not None:
                self.require_current_admin(connection, actor_token, actor_id)
            connection.execute(
                "INSERT INTO users VALUES (?,?,?,?,?,?,?,?,?)",
                (subject.user_id, username.strip(), salt, hashed, role,
                 department_id, clearance, 1, 1))
            if actor_id is not None:
                self._audit(connection, actor_id, "user.create", subject.user_id, 1)
        return subject

    def login(self, username: str, password: str, *, now: float | None = None) -> str:
        if not isinstance(username, str) or not isinstance(password, str):
            raise AuthenticationError()
        if len(username) > 64 or len(password) > 1024:
            raise AuthenticationError()
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM users WHERE username=?",
                                     (username.strip(),)).fetchone()
        # Perform the same expensive operation for unknown usernames.
        salt = bytes(row["password_salt"]) if row else bytes(16)
        supplied = _password_hash(password, salt)
        expected = bytes(row["password_hash"]) if row else bytes(32)
        matches = hmac.compare_digest(supplied, expected)
        if row is None or not matches or not row["active"]:
            raise AuthenticationError()
        token = secrets.token_urlsafe(32)
        with self.connect() as connection:
            # Recheck after password hashing; disable/rekey can occur concurrently.
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute("SELECT * FROM users WHERE user_id=?",
                                         (row["user_id"],)).fetchone()
            if (not current or not current["active"]
                    or current["authz_version"] != row["authz_version"]):
                raise AuthenticationError()
            connection.execute("INSERT INTO sessions VALUES (?,?,?,0)",
                               (_digest(token), row["user_id"],
                                (time.time() if now is None else now) + SESSION_SECONDS))
        return token

    def authenticate(self, token: str, *, now: float | None = None) -> UserContext:
        if not isinstance(token, str) or not 20 <= len(token) <= 256:
            raise AuthenticationError()
        with self.connect() as connection:
            row = connection.execute(
                """SELECT u.* FROM users u JOIN sessions s ON u.user_id=s.user_id
                   WHERE s.token_hash=? AND s.revoked=0 AND s.expires_at>?
                   AND u.active=1""",
                (_digest(token), time.time() if now is None else now)).fetchone()
        if row is None:
            raise AuthenticationError()
        return UserContext(user_id=row["user_id"], role=row["role"],
                           department_id=row["department_id"], clearance=row["clearance"],
                           active=bool(row["active"]), authz_version=row["authz_version"])

    def logout(self, token: str):
        self.authenticate(token)
        with self.connect() as connection:
            connection.execute("UPDATE sessions SET revoked=1 WHERE token_hash=?",
                               (_digest(token),))

    def change_access(self, user_id: str, *, role: str, department_id: str,
                      clearance: int, active: bool,
                      actor_id: str | None = None, actor_token: str | None = None) -> UserContext:
        proposed = UserContext(user_id=user_id, role=role, department_id=department_id,
                               clearance=clearance, active=active, authz_version=1)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if actor_token is not None:
                self.require_current_admin(connection, actor_token, actor_id)
            row = connection.execute("SELECT authz_version FROM users WHERE user_id=?",
                                     (user_id,)).fetchone()
            if row is None:
                raise ValueError("Unknown user")
            version = row["authz_version"] + 1
            connection.execute(
                """UPDATE users SET role=?, department_id=?, clearance=?, active=?,
                   authz_version=? WHERE user_id=?""",
                (role, department_id, clearance, int(active), version, user_id))
            # All previous tokens are revoked; re-enabling cannot revive them.
            connection.execute("UPDATE sessions SET revoked=1 WHERE user_id=?", (user_id,))
            if actor_id is not None:
                self._audit(connection, actor_id, "user.access", user_id, version)
        return proposed.model_copy(update={"authz_version": version})

    @staticmethod
    def require_current_admin(connection, token, actor_id):
        """Call while holding the access database write transaction."""
        row = connection.execute(
            """SELECT 1 FROM sessions s JOIN users u ON u.user_id=s.user_id
               WHERE s.token_hash=? AND s.revoked=0 AND s.expires_at>?
               AND u.user_id=? AND u.active=1 AND u.role='admin'""",
            (_digest(token), time.time(), actor_id)).fetchone()
        if row is None:
            raise AuthenticationError()

    @staticmethod
    def _audit(connection, actor_id, action, user_id, version):
        connection.execute("INSERT INTO audit_events VALUES (NULL,?,?,?,?,?)",
                           (actor_id, action, user_id, version, time.time()))

    def management_page(self, *, limit: int, offset: int) -> dict:
        """Explicit safe projection; HTTP caller must check administrator identity."""
        if type(limit) is not int or type(offset) is not int or not 1 <= limit <= 50 or not 0 <= offset <= 100000:
            raise ValueError("Invalid pagination")
        with self.connect() as connection:
            connection.execute("BEGIN")
            total = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            items = []
            for row in connection.execute(
                """SELECT user_id, username, role, department_id, clearance, active, authz_version
                   FROM users ORDER BY username, user_id LIMIT ? OFFSET ?""", (limit, offset)):
                person = UserContext(user_id=row["user_id"], role=row["role"],
                    department_id=row["department_id"], clearance=row["clearance"],
                    active=bool(row["active"]), authz_version=row["authz_version"])
                items.append(person.model_dump() | {"username": row["username"]})
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    def change_own_password(self, token: str, current_password: str, new_password: str):
        person = self.authenticate(token)
        _validate_password(new_password)
        if not isinstance(current_password, str) or not 1 <= len(current_password) <= 1024:
            raise AuthenticationError()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT password_salt, password_hash, authz_version FROM users WHERE user_id=?",
                (person.user_id,)).fetchone()
        if row is None or not hmac.compare_digest(
                _password_hash(current_password, bytes(row["password_salt"])),
                bytes(row["password_hash"])):
            raise AuthenticationError()
        salt = secrets.token_bytes(16)
        hashed = _password_hash(new_password, salt)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                """SELECT u.authz_version FROM users u JOIN sessions s ON s.user_id=u.user_id
                   WHERE u.user_id=? AND u.active=1 AND s.token_hash=?
                   AND s.revoked=0 AND s.expires_at>?""",
                (person.user_id, _digest(token), time.time())).fetchone()
            if (current is None or current["authz_version"] != person.authz_version
                    or row["authz_version"] != person.authz_version):
                raise AuthenticationError()
            connection.execute(
                """UPDATE users SET password_salt=?, password_hash=?, authz_version=authz_version+1
                   WHERE user_id=?""", (salt, hashed, person.user_id))
            connection.execute("UPDATE sessions SET revoked=1 WHERE user_id=?", (person.user_id,))
            self._audit(connection, person.user_id, "user.password", person.user_id,
                        person.authz_version + 1)

    def change_password(self, user_id: str, password: str):
        _validate_password(password)
        salt = secrets.token_bytes(16)
        hashed = _password_hash(password, salt)
        with self.connect() as connection:
            result = connection.execute(
                """UPDATE users SET password_salt=?, password_hash=?,
                   authz_version=authz_version+1 WHERE user_id=?""",
                (salt, hashed, user_id))
            if result.rowcount != 1:
                raise ValueError("Unknown user")
            connection.execute("UPDATE sessions SET revoked=1 WHERE user_id=?", (user_id,))
