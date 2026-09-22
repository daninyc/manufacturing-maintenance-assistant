"""HTTP 入口：恢复可信身份，提供问答、诊断及管理接口，统一隐藏错误细节。

客户端自报角色不作为授权依据；当前内存限速要求单 worker。
"""
import asyncio
import hashlib
import os
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError
from starlette.concurrency import run_in_threadpool

from app.auth.sessions import AuthenticationError, SessionStore
from app.core.config import DATABASE_PATH, PROJECT_ROOT
from app.db.session import read_connection
from app.ingestion.publication import publish_document
from app.schemas.diagnosis import DiagnoseRequest, TimeRange
from app.schemas.qa import AskRequest
from app.security.authorization import (
    ResourcePolicy,
    Role,
    UserContext,
    can_manage,
    can_read,
    permitted_chunk,
)
from app.security.policies import PolicyConflict, PolicyStore
from app.services.diagnosis_service import diagnose
from app.services.protected_data import ProtectedMaintenance, ResourceUnavailable
from app.services.protected_qa import authorized_answer


class ProtectedQuestion(AskRequest):
    model_config = ConfigDict(extra="forbid", strict=True)
    mode: Literal["local", "deepseek"] = "local"


class ProtectedDiagnosis(DiagnoseRequest):
    mode: Literal["local", "deepseek"] = "local"


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    username: str = Field(min_length=1, max_length=64)
    password: SecretStr = Field(min_length=1, max_length=1024)


class ChangePassword(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    current_password: SecretStr = Field(min_length=1, max_length=1024)
    new_password: SecretStr = Field(min_length=12, max_length=1024)


class CreateUser(Login):
    password: SecretStr = Field(min_length=12, max_length=1024)
    role: Role
    department_id: str = Field(min_length=1, max_length=64)
    clearance: int = Field(ge=0, le=2)


class ChangeAccess(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    role: Role
    department_id: str = Field(min_length=1, max_length=64)
    clearance: int = Field(ge=0, le=2)
    active: bool


class PolicyChange(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_version: int = Field(ge=0)
    policy: ResourcePolicy


def query_time_range(start_time: datetime | None = None, end_time: datetime | None = None):
    try:
        return TimeRange(start_time=start_time, end_time=end_time)
    except ValidationError:
        raise HTTPException(422, "INPUT_ERROR") from None


class LoginLimiter:
    """Bounded fixed-window limiter, per source and username; single-worker deployment."""

    def __init__(self):
        self.entries = {}
        self.lock = threading.Lock()

    def check(self, source: str, username: str):
        now = time.monotonic()
        keys = [("source", source, 30),
                ("account", hashlib.sha256(username.strip().encode()).hexdigest(), 10)]
        with self.lock:
            self.entries = {k: v for k, v in self.entries.items() if v[0] > now}
            if len(self.entries) >= 10000:
                raise HTTPException(429, "RATE_LIMITED")
            for kind, value, limit in keys:
                deadline, count = self.entries.get((kind, value), (now + 60, 0))
                if count >= limit:
                    raise HTTPException(429, "RATE_LIMITED")
            for kind, value, _ in keys:
                deadline, count = self.entries.get((kind, value), (now + 60, 0))
                self.entries[(kind, value)] = (deadline, count + 1)


def create_app(access_path: Path | None = None, business_path: Path | None = None,
               vector_path: Path | None = None) -> FastAPI:
    app = FastAPI(title="Maintenance Assistant", docs_url=None, redoc_url=None,
                  openapi_url=None)
    sessions = SessionStore(access_path or PROJECT_ROOT / os.getenv(
        "ACCESS_DATABASE_PATH", "data/access.sqlite3"))
    policies = PolicyStore(sessions)
    app.state.sessions = sessions
    app.state.policies = policies
    business = ProtectedMaintenance(business_path or DATABASE_PATH, sessions)
    app.state.business = business
    app.state.vector_store = None
    vector_lock = threading.Lock()
    limiter = LoginLimiter()
    bearer = HTTPBearer(auto_error=False)

    @app.middleware("http")
    async def response_headers(request: Request, call_next):
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def failure(request, code, status):
        return JSONResponse({"code": code, "request_id": request.state.request_id},
                            status_code=status)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Never reflect login input, passwords or payloads in validation errors.
        return failure(request, "INPUT_ERROR", 422)

    @app.exception_handler(AuthenticationError)
    async def invalid_auth(request, exc):
        return failure(request, "AUTHENTICATION_REQUIRED", 401)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return failure(request, exc.detail, exc.status_code)

    @app.exception_handler(sqlite3.Error)
    async def database_error(request, exc):
        return failure(request, "DATABASE_UNAVAILABLE", 503)

    @app.exception_handler(RuntimeError)
    async def unavailable(request, exc):
        return failure(request, "SERVICE_UNAVAILABLE", 503)

    @app.exception_handler(ResourceUnavailable)
    async def resource_unavailable(request, exc):
        return failure(request, "RESOURCE_UNAVAILABLE", 404)

    @app.exception_handler(PolicyConflict)
    async def conflict(request, exc):
        return failure(request, "POLICY_CONFLICT", 409)

    def credential(value: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> str:
        if value is None:
            raise AuthenticationError()
        sessions.authenticate(value.credentials)
        return value.credentials

    def subject(token: Annotated[str, Depends(credential)]) -> UserContext:
        return sessions.authenticate(token)

    def administrator(person: Annotated[UserContext, Depends(subject)]) -> UserContext:
        if not can_manage(person):
            raise HTTPException(403, "FORBIDDEN")
        return person

    @app.get("/health/live")
    def live():
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready(request: Request, person: Annotated[UserContext, Depends(administrator)]):
        with sessions.connect() as db:
            for table in ("users", "sessions", "documents", "equipment_policies",
                          "alarm_policies", "maintenance_policies", "audit_events"):
                db.execute(f"SELECT 1 FROM {table} LIMIT 1")
        with read_connection(business.path, request.state.request_id) as db:
            for table in ("equipment", "alarms", "maintenance_records"):
                db.execute(f"SELECT 1 FROM {table} LIMIT 1")
        return {"status": "ok", "scope": "authentication-policy-business-databases",
                "not_checked": ["vector-index", "embedding-model", "cloud-model", "client-connectivity"]}

    @app.post("/api/v1/auth/login")
    def login(payload: Login, request: Request):
        limiter.check(request.client.host if request.client else "unknown", payload.username)
        token = sessions.login(payload.username, payload.password.get_secret_value())
        return {"access_token": token, "token_type": "bearer", "expires_in": 3600}

    @app.post("/api/v1/auth/logout")
    def logout(token: Annotated[str, Depends(credential)]):
        sessions.logout(token)
        return {"ok": True}

    @app.post("/api/v1/auth/password")
    def password_change(payload: ChangePassword, request: Request,
                         token: Annotated[str, Depends(credential)]):
        person = sessions.authenticate(token)
        limiter.check(request.client.host if request.client else "unknown", "password:" + person.user_id)
        sessions.change_own_password(token, payload.current_password.get_secret_value(),
                                     payload.new_password.get_secret_value())
        return {"ok": True, "reauthentication_required": True}

    @app.get("/api/v1/me")
    def me(person: Annotated[UserContext, Depends(subject)]):
        return person

    @app.get("/api/v1/admin/users")
    def managed_users(admin: Annotated[UserContext, Depends(administrator)],
                       token: Annotated[str, Depends(credential)],
                       limit: Annotated[int, Field(ge=1, le=50)] = 20,
                       offset: Annotated[int, Field(ge=0, le=100000)] = 0):
        result = sessions.management_page(limit=limit, offset=offset)
        if sessions.authenticate(token) != admin:
            raise AuthenticationError()
        return result

    @app.post("/api/v1/admin/users", status_code=201)
    def create_user(payload: CreateUser, admin: Annotated[UserContext, Depends(administrator)],
                    token: Annotated[str, Depends(credential)]):
        try:
            person = sessions.create_user(payload.username, payload.password.get_secret_value(),
                                          role=payload.role, department_id=payload.department_id,
                                          clearance=payload.clearance, actor_id=admin.user_id, actor_token=token)
        except sqlite3.IntegrityError:
            raise HTTPException(409, "USER_CONFLICT") from None
        return person

    @app.patch("/api/v1/admin/users/{user_id}")
    def change_access(user_id: str, payload: ChangeAccess,
                      admin: Annotated[UserContext, Depends(administrator)],
                      token: Annotated[str, Depends(credential)]):
        try:
            person = sessions.change_access(user_id, **payload.model_dump(), actor_id=admin.user_id,
                                            actor_token=token)
        except AuthenticationError:
            raise
        except ValueError:
            raise HTTPException(422, "INPUT_ERROR") from None
        return person

    @app.patch("/api/v1/admin/documents/{document_id}/policy")
    def change_policy(document_id: str, payload: PolicyChange,
                      admin: Annotated[UserContext, Depends(administrator)],
                      token: Annotated[str, Depends(credential)]):
        if document_id != payload.policy.resource_id:
            raise HTTPException(422, "INPUT_ERROR")
        policies.save(payload.policy, expected_version=payload.expected_version,
                      actor_id=admin.user_id, actor_token=token)
        return payload.policy

    @app.get("/api/v1/documents")
    def documents(person: Annotated[UserContext, Depends(subject)]):
        # Metadata stays server-side unless the same read policy permits it.
        return [p for p in policies.list_policies() if can_read(person, p)]

    @app.get("/api/v1/admin/documents")
    def managed_documents(admin: Annotated[UserContext, Depends(administrator)],
                           token: Annotated[str, Depends(credential)],
                           limit: Annotated[int, Field(ge=1, le=50)] = 20,
                           offset: Annotated[int, Field(ge=0, le=100000)] = 0):
        result = policies.management_page(limit=limit, offset=offset)
        if sessions.authenticate(token) != admin:
            raise AuthenticationError()
        return result

    @app.patch("/api/v1/admin/resources/{kind}/{resource_id}/policy")
    def change_business_policy(kind: Literal["equipment", "alarm", "maintenance"],
                               resource_id: str, payload: PolicyChange,
                               admin: Annotated[UserContext, Depends(administrator)],
                               token: Annotated[str, Depends(credential)]):
        if resource_id != payload.policy.resource_id:
            raise HTTPException(422, "INPUT_ERROR")
        business.stores[kind].save(payload.policy, expected_version=payload.expected_version,
                                  actor_id=admin.user_id, actor_token=token)
        return payload.policy

    @app.get("/api/v1/equipment")
    def equipment_list(token: Annotated[str, Depends(credential)],
                       limit: Annotated[int, Field(ge=1, le=50)] = 20,
                       offset: Annotated[int, Field(ge=0, le=100000)] = 0):
        return business.list_equipment(token, limit=limit, offset=offset)

    @app.get("/api/v1/equipment/{equipment_id}")
    def equipment_detail(equipment_id: str, token: Annotated[str, Depends(credential)]):
        return business.query(token, "equipment", equipment_id)

    @app.get("/api/v1/equipment/{equipment_id}/alarms")
    def alarms(equipment_id: str, token: Annotated[str, Depends(credential)],
               period: Annotated[TimeRange, Depends(query_time_range)],
               limit: Annotated[int, Field(ge=1, le=50)] = 5,
               severity: Literal["info", "warning", "critical"] | None = None):
        return business.query(token, "alarms", equipment_id, limit=limit, severity=severity,
                              **period.model_dump())

    @app.get("/api/v1/equipment/{equipment_id}/maintenance")
    def maintenance(equipment_id: str, token: Annotated[str, Depends(credential)],
                    period: Annotated[TimeRange, Depends(query_time_range)],
                    limit: Annotated[int, Field(ge=1, le=50)] = 5):
        return business.query(token, "maintenance", equipment_id, limit=limit, **period.model_dump())

    def vector_store():
        with vector_lock:
            if app.state.vector_store is None:
                from app.retrieval.vector_store import LocalChromaStore
                app.state.vector_store = LocalChromaStore(
                    vector_path or PROJECT_ROOT / "data/chroma", "authorized_v1", semantic=True)
        return app.state.vector_store

    @app.post("/api/v1/admin/documents/{document_id}/content", status_code=201)
    async def upload_document(document_id: str, request: Request,
                              admin: Annotated[UserContext, Depends(administrator)],
                              token: Annotated[str, Depends(credential)],
                              expected_version: Annotated[int, Field(ge=1)],
                              format: Literal["txt", "pdf"],
                              equipment_id: Annotated[str, Field(max_length=128)] = ""):
        proposed = policies.get_many([document_id]).get(document_id)
        if proposed is None:
            raise HTTPException(404, "RESOURCE_UNAVAILABLE")
        if proposed.policy_version != expected_version or proposed.status != "draft":
            raise HTTPException(409, "POLICY_CONFLICT")
        expected_type = "text/plain" if format == "txt" else "application/pdf"
        if request.headers.get("content-type", "").split(";", 1)[0].strip() != expected_type:
            raise HTTPException(415, "UNSUPPORTED_MEDIA_TYPE")
        maximum = 10 * 1024 * 1024
        length = request.headers.get("content-length")
        if length is not None:
            if not length.isdecimal():
                raise HTTPException(422, "INPUT_ERROR")
            if int(length) > maximum:
                raise HTTPException(413, "DOCUMENT_TOO_LARGE")
        content = bytearray()
        try:
            async with asyncio.timeout(60):
                async for part in request.stream():
                    if len(content) + len(part) > maximum:
                        raise HTTPException(413, "DOCUMENT_TOO_LARGE")
                    content.extend(part)
        except TimeoutError:
            raise HTTPException(408, "UPLOAD_TIMEOUT") from None
        if not content or (format == "pdf" and not content.startswith(b"%PDF-")):
            raise HTTPException(422, "INPUT_ERROR")

        def persist_and_publish():
            # Recheck after network input; client names never participate in file paths.
            if sessions.authenticate(token) != admin:
                raise AuthenticationError()
            directory = sessions.path.parent / "uploads"
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / (uuid4().hex + "." + format)
            created = False
            published = False
            try:
                with path.open("xb") as target:
                    created = True
                    target.write(content)
                result = publish_document(path, proposed, vector_store(), policies, sessions,
                                          token, expected_version=expected_version,
                                          equipment_id=equipment_id)
                published = True
                return result
            except (AuthenticationError, PolicyConflict):
                raise
            except PermissionError:
                raise HTTPException(403, "FORBIDDEN") from None
            except ValueError:
                raise HTTPException(422, "INPUT_ERROR") from None
            except OSError:
                raise HTTPException(503, "STORAGE_UNAVAILABLE") from None
            finally:
                # Keep successful originals server-side; clean only this request's failed file.
                if created and not published:
                    path.unlink(missing_ok=True)
        result = await run_in_threadpool(persist_and_publish)
        return {"document_id": result.resource_id, "status": result.status,
                "policy_version": result.policy_version, "content_version": result.content_version}

    @app.post("/api/v1/ask")
    def ask(payload: ProtectedQuestion, token: Annotated[str, Depends(credential)]):
        # Lazy local index opening only after authentication; isolated from legacy collections.
        return authorized_answer(
            vector_store(), policies, sessions, token,
            AskRequest(**payload.model_dump(exclude={"mode"})), mode=payload.mode)

    @app.post("/api/v1/diagnose")
    def diagnosis(payload: ProtectedDiagnosis, token: Annotated[str, Depends(credential)]):
        # Reject an inaccessible device before opening the vector index.
        business.query(token, "equipment", payload.equipment_id)
        return diagnose(business, vector_store(), token,
                        DiagnoseRequest(**payload.model_dump(exclude={"mode"})), mode=payload.mode)

    @app.get("/api/v1/documents/{document_id}/chunks/{chunk_id}")
    def citation(document_id: str, chunk_id: str,
                 token: Annotated[str, Depends(credential)]):
        person = sessions.authenticate(token)
        labels = policies.get_many([document_id])
        if not can_read(person, labels.get(document_id)):
            raise HTTPException(404, "RESOURCE_UNAVAILABLE")
        found = vector_store().collection.get(ids=[chunk_id],
                                              include=["documents", "metadatas"])
        if not found["ids"]:
            raise HTTPException(404, "RESOURCE_UNAVAILABLE")
        metadata = found["metadatas"][0]
        if (metadata.get("document_id") != document_id
                or not permitted_chunk(person, metadata, labels)):
            raise HTTPException(404, "RESOURCE_UNAVAILABLE")
        current = sessions.authenticate(token)
        if current != person or not permitted_chunk(
                current, metadata, policies.get_many([document_id])):
            raise HTTPException(404, "RESOURCE_UNAVAILABLE")
        return {"document_id": document_id, "chunk_id": chunk_id,
                "policy_version": metadata["policy_version"],
                "content_version": metadata["content_version"],
                "source_file": metadata["source_file"], "page": metadata.get("page"),
                "excerpt": found["documents"][0]}

    return app


app = create_app()
