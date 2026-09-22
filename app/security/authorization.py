"""统一授权：角色决定动作，部门与密级限定资源范围，缺失策略默认拒绝。

数据库策略是权威来源，向量标签不能授予权限；管理员没有跨部门正文读取特权。
"""
from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Role = Literal["employee", "engineer", "admin"]


class UserContext(BaseModel):
    """Construct only from the current server-side session/user record."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    user_id: str = Field(min_length=1, max_length=64)
    role: Role
    department_id: str = Field(min_length=1, max_length=64)
    clearance: int = Field(ge=0, le=2)
    active: bool
    authz_version: int = Field(ge=1)

    @model_validator(mode="after")
    def nonblank_identity(self):
        if not self.user_id.strip() or not self.department_id.strip():
            raise ValueError("Identity fields must not be blank")
        return self


class ResourcePolicy(BaseModel):
    """Database policy is authoritative; vector metadata is only a hint."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    resource_id: str = Field(min_length=1, max_length=128)
    department_id: str = Field(min_length=1, max_length=64)
    visibility: Literal["organization", "department"]
    classification: int = Field(ge=0, le=2)
    status: Literal["draft", "indexing", "active", "disabled", "failed"]
    policy_version: int = Field(ge=1)
    content_version: str = Field(min_length=1, max_length=128)
    external_processing_allowed: bool = False

    @model_validator(mode="after")
    def nonblank_resource(self):
        if any(not value.strip() for value in
               (self.resource_id, self.department_id, self.content_version)):
            raise ValueError("Policy fields must not be blank")
        return self


def can_read(user: UserContext, policy: ResourcePolicy | None) -> bool:
    """Roles grant the read action, never a cross-department admin bypass."""
    return (
        user.active
        and policy is not None
        and policy.status == "active"
        and user.clearance >= policy.classification
        and (policy.visibility == "organization"
             or user.department_id == policy.department_id)
    )


def can_manage(user: UserContext) -> bool:
    """Management permission does not imply permission to read a document."""
    return user.active and user.role == "admin"


def can_process_externally(user: UserContext, policy: ResourcePolicy | None) -> bool:
    return can_read(user, policy) and policy.external_processing_allowed


def permitted_chunk(user: UserContext, metadata: Mapping,
                    policies: Mapping[str, ResourcePolicy]) -> bool:
    """Fail closed on missing/stale versions. Ignore candidate clearance claims."""
    document_id = metadata.get("document_id")
    if not isinstance(document_id, str):
        return False
    policy = policies.get(document_id)
    return (
        can_read(user, policy)
        and policy.resource_id == document_id
        and type(metadata.get("policy_version")) is int
        and metadata["policy_version"] == policy.policy_version
        and metadata.get("content_version") == policy.content_version
        and isinstance(metadata.get("chunk_id"), str)
        and bool(metadata["chunk_id"].strip())
    )


def filter_authorized_chunks(user: UserContext, chunks: Sequence,
                             policies: Mapping[str, ResourcePolicy]) -> list:
    """Call before traces, candidate excerpts, external processing or responses."""
    return [chunk for chunk in chunks if permitted_chunk(user, chunk.metadata, policies)]
