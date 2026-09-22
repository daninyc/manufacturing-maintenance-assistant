from dataclasses import dataclass
from itertools import product

import pytest
from pydantic import ValidationError

from app.security.authorization import (
    ResourcePolicy,
    UserContext,
    can_manage,
    can_process_externally,
    can_read,
    filter_authorized_chunks,
    permitted_chunk,
)


def user(**changes):
    return UserContext(**({"user_id": "A1", "role": "employee", "department_id": "A",
                          "clearance": 1, "active": True, "authz_version": 1} | changes))


def policy(**changes):
    return ResourcePolicy(**({"resource_id": "DOC-A", "department_id": "A",
                              "visibility": "department", "classification": 1,
                              "status": "active", "policy_version": 1,
                              "content_version": "v1"} | changes))


@pytest.mark.parametrize("subject,resource,allowed", [
    (user(), policy(), True),
    (user(clearance=0), policy(), False),
    (user(department_id="B", clearance=2), policy(), False),
    (user(department_id="B"), policy(visibility="organization"), True),
    (user(role="admin", department_id="B", clearance=2), policy(), False),
    (user(role="admin"), policy(), True),
    (user(active=False), policy(), False),
    (user(), None, False),
    (user(), policy(status="draft"), False),
    (user(), policy(status="indexing"), False),
    (user(), policy(status="disabled"), False),
    (user(), policy(status="failed"), False),
])
def test_read_matrix(subject, resource, allowed):
    assert can_read(subject, resource) is allowed


def test_complete_policy_attribute_matrix():
    """穷举合法属性的 2160 个组合；这是规则层覆盖，不冒充 2160 个端到端场景。"""
    checked = 0
    for role, active, department, clearance, classification, visibility, status, external in product(
        ("employee", "engineer", "admin"), (True, False), ("A", "B"), range(3), range(3),
        ("department", "organization"), ("draft", "indexing", "active", "disabled", "failed"),
        (True, False),
    ):
        subject = user(role=role, active=active, department_id=department, clearance=clearance)
        resource = policy(classification=classification, visibility=visibility, status=status,
                          external_processing_allowed=external)
        # 采用逐项拒绝定义验收期望，避免以待测函数的结果生成期望。
        denial_reasons = [not active, status != "active", clearance < classification,
                          visibility == "department" and department != "A"]
        allowed = not any(denial_reasons)
        context = (role, active, department, clearance, classification, visibility, status, external)
        assert can_read(subject, resource) is allowed, context
        assert can_process_externally(subject, resource) is (allowed and external), context
        assert can_manage(subject) is (active and role == "admin"), context
        checked += 1
    assert checked == 2160


@pytest.mark.parametrize("changes", [
    {"role": "root"}, {"clearance": 3}, {"clearance": True},
    {"clearance": "2"}, {"active": 1}, {"authz_version": 0},
    {"department_id": " "}, {"user_id": " "},
])
def test_identity_rejects_invalid_values(changes):
    with pytest.raises(ValidationError):
        user(**changes)


@pytest.mark.parametrize("changes", [
    {"classification": -1}, {"classification": True},
    {"visibility": ""}, {"department_id": " "}, {"policy_version": 0},
    {"content_version": " "}, {"external_processing_allowed": "true"},
])
def test_policy_rejects_invalid_values(changes):
    with pytest.raises(ValidationError):
        policy(**changes)


def test_missing_labels_cannot_be_parsed():
    with pytest.raises(ValidationError):
        ResourcePolicy(resource_id="DOC-A")


def test_manage_does_not_grant_read():
    admin = user(role="admin", department_id="B")
    assert can_manage(admin)
    assert not can_read(admin, policy())
    assert not can_manage(user())
    assert not can_manage(user(role="admin", active=False))


def test_external_processing_needs_both_permissions():
    assert not can_process_externally(user(), policy())
    enabled = policy(external_processing_allowed=True)
    assert can_process_externally(user(), enabled)
    assert not can_process_externally(user(department_id="B"), enabled)
    assert not can_process_externally(user(), None)


def metadata(**changes):
    return {"document_id": "DOC-A", "chunk_id": "DOC-A::page-1::chunk-0000",
            "content_version": "v1", "policy_version": 1} | changes


@pytest.mark.parametrize("changes", [
    {"document_id": "UNKNOWN"}, {"content_version": "old"},
    {"policy_version": 0}, {"policy_version": True},
    {"policy_version": "1"}, {"chunk_id": ""},
])
def test_invalid_or_stale_candidate_rejected(changes):
    assert not permitted_chunk(user(), metadata(**changes), {"DOC-A": policy()})


def test_forged_vector_labels_do_not_grant_permission():
    forged = metadata(classification=0, visibility="organization", department_id="B")
    assert not permitted_chunk(user(department_id="B"), forged, {"DOC-A": policy()})


def test_revoke_or_disable_invalidates_same_candidate():
    candidate = metadata()
    assert permitted_chunk(user(), candidate, {"DOC-A": policy()})
    assert not permitted_chunk(user(), candidate, {"DOC-A": policy(policy_version=2)})
    assert not permitted_chunk(user(), candidate, {"DOC-A": policy(status="disabled")})


def test_policy_map_identity_mismatch_rejected():
    assert not permitted_chunk(user(), metadata(), {"DOC-A": policy(resource_id="OTHER")})


def test_batch_filter_removes_secret_without_mutation():
    @dataclass
    class Chunk:
        text: str
        metadata: dict

    chunks = [
        Chunk("readable", metadata()),
        Chunk("SIM_SECRET_B", metadata(document_id="DOC-B")),
        Chunk("untagged", {}),
    ]
    policies = {"DOC-A": policy(),
                "DOC-B": policy(resource_id="DOC-B", department_id="B")}
    result = filter_authorized_chunks(user(), chunks, policies)
    assert [chunk.text for chunk in result] == ["readable"]
    assert len(chunks) == 3
    assert filter_authorized_chunks(user(), chunks, {}) == []
