import hashlib
import os

import pytest
from fastapi.testclient import TestClient

from app.api.server import create_app
from app.auth.sessions import SessionStore
from app.core.config import PROJECT_ROOT
from app.db.repositories import MaintenanceRepository
from app.db.seed import seed_database
from app.retrieval.vector_store import LocalChromaStore
from app.schemas.diagnosis import DiagnoseRequest
from app.security.authorization import ResourcePolicy
from app.services.diagnosis_service import diagnose
from app.services.evidence import EvidenceQuote, EvidenceSelection
from app.services.protected_data import ProtectedMaintenance, ResourceUnavailable
from scripts.label_equipment import label_equipment


@pytest.fixture
def system(tmp_path):
    path = tmp_path / "business.sqlite3"
    seed_database(path)
    sessions = SessionStore(tmp_path / "access.sqlite3")
    business = ProtectedMaintenance(path, sessions)
    for policy_store in business.stores.values():
        policy_store.initialize()
    sessions.create_user("admin", "test-only-password", role="admin", department_id="A", clearance=2)
    sessions.create_user("reader", "test-only-password", role="engineer", department_id="A", clearance=1)
    admin = sessions.login("admin", "test-only-password")
    label_equipment(sessions, admin, path, "EQ-ROBOT-001", department="A", classification=1)
    repository = MaintenanceRepository(path)
    ids = {r.document_id for r in repository.list_recent_alarms("EQ-ROBOT-001")}
    ids.update(r.document_id for r in repository.list_maintenance_history("EQ-ROBOT-001"))
    for document_id in ids:
        business.stores["document"].save(ResourcePolicy(
            resource_id=document_id, department_id="A", visibility="department", classification=1,
            status="active", policy_version=1, content_version="v1"),
            expected_version=0, actor_id="test-admin")
    store = LocalChromaStore(tmp_path / "chroma", "diagnosis-test")
    return business, store, sessions.login("reader", "test-only-password")


def test_history_is_evidence_not_current_repair_permission(system):
    business, store, token = system
    response = diagnose(business, store, token, DiagnoseRequest(
        equipment_id="EQ-ROBOT-001", symptom="模拟异常"))
    assert {e.source_type for e in response.evidence} == {"alarm", "maintenance"}
    assert response.status == "human_review"
    assert response.suggestions == [] and not response.grounded
    assert all(e.policy_version == 1 and e.document_id for e in response.evidence)


@pytest.mark.skipif(os.getenv("RUN_LIVE_DEEPSEEK") != "1", reason="Explicit live-model opt-in required")
def test_live_three_source_diagnosis_with_real_bge(system, tmp_path):
    """真实云端验收：仅临时模拟数据，捕获来源类型而不记录请求正文或凭证。"""
    from app.services.diagnosis_selection import request_selection

    business, _, token = system
    for policy_store in business.stores.values():
        for old in policy_store.list_policies():
            policy_store.save(old.model_copy(update={
                "external_processing_allowed": True, "policy_version": old.policy_version + 1}),
                expected_version=old.policy_version, actor_id="test-admin")
    policy = business.stores["document"].list_policies()[0]
    text = "模拟异常需要登记并转人工核查。"
    store = LocalChromaStore(tmp_path / "live-bge", "live_diagnosis", semantic=True)
    store.upsert(ids=["live-knowledge"], documents=[text], metadatas=[{
        "chunk_id": "live-knowledge", "document_id": policy.resource_id,
        "source_file": "simulation.txt", "policy_version": policy.policy_version,
        "content_version": policy.content_version, "equipment_id": "EQ-ROBOT-001"}])
    calls = []
    def real_transport(payload):
        calls.append({e["source_type"] for e in payload["evidence"]})
        return request_selection(payload)
    response = diagnose(business, store, token, DiagnoseRequest(
        equipment_id="EQ-ROBOT-001", symptom=text), mode="deepseek",
        diagnosis_transport=real_transport)
    assert calls == [{"knowledge", "alarm", "maintenance"}]
    assert response.evidence
    assert response.status == "human_review"
    assert not response.grounded and response.suggestions == []
    assert all(e.policy_version == 2 for e in response.evidence)


def test_inaccessible_device_never_reaches_vector_store(system):
    business, _, token = system
    with pytest.raises(ResourceUnavailable):
        diagnose(business, None, token, DiagnoseRequest(
            equipment_id="EQ-ROBOT-002", symptom="模拟异常"))


def test_document_selection_and_inflight_revocation(system):
    business, store, token = system
    policy = business.stores["document"].list_policies()[0]
    text = "模拟异常需要登记并转人工核查。"
    store.upsert(ids=["test-chunk"], documents=[text], metadatas=[{
        "chunk_id": "test-chunk", "document_id": policy.resource_id,
        "source_file": "simulation.txt", "policy_version": 1, "content_version": "v1",
        "equipment_id": "EQ-ROBOT-001"}])

    def select(question, chunks):
        return EvidenceSelection(supported=True, quotes=[EvidenceQuote(chunk_id="test-chunk", excerpt=text)])

    request = DiagnoseRequest(equipment_id="EQ-ROBOT-001", symptom=text)
    result = diagnose(business, store, token, request, selector=select)
    assert {e.source_type for e in result.evidence} == {"knowledge", "alarm", "maintenance"}

    def revoke(question, chunks):
        old = business.stores["equipment"].get_many(["EQ-ROBOT-001"])["EQ-ROBOT-001"]
        business.stores["equipment"].save(
            old.model_copy(update={"status": "disabled", "policy_version": 2}),
            expected_version=1, actor_id="test-admin")
        return select(question, chunks)

    with pytest.raises(ResourceUnavailable):
        diagnose(business, store, token, request, selector=revoke)


def test_diagnosis_http_auth_and_input(system):
    business, store, token = system
    app = create_app(business.sessions.path, business.path)
    app.state.vector_store = store
    client = TestClient(app)
    body = {"equipment_id": "EQ-ROBOT-001", "symptom": "模拟异常"}
    auth = {"Authorization": "Bearer " + token}
    assert client.post("/api/v1/diagnose", json=body).status_code == 401
    assert client.post("/api/v1/diagnose", json={**body, "role": "admin"}, headers=auth).status_code == 422
    result = client.post("/api/v1/diagnose", json=body, headers=auth)
    assert result.status_code == 200 and result.json()["suggestions"] == []


def test_business_external_denial_never_sends_records(system):
    business, store, token = system
    def forbidden(payload):
        pytest.fail("Business records must not be sent without external permission")
    with pytest.raises(ResourceUnavailable):
        diagnose(business, store, token, DiagnoseRequest(
            equipment_id="EQ-ROBOT-001", symptom="模拟异常"), mode="deepseek", diagnosis_transport=forbidden)


@pytest.mark.parametrize("revoke", [False, True])
def test_business_selection_checks_permissions_after_model(system, revoke):
    business, store, token = system
    for policy_store in business.stores.values():
        for old in policy_store.list_policies():
            policy_store.save(old.model_copy(update={
                "external_processing_allowed": True, "policy_version": old.policy_version + 1}),
                expected_version=old.policy_version, actor_id="test-admin")
    def transport(payload):
        assert {e["source_type"] for e in payload["evidence"]} == {"alarm", "maintenance"}
        if revoke:
            policy_store = business.stores["equipment"]
            old = policy_store.list_policies()[0]
            policy_store.save(old.model_copy(update={"status": "disabled", "policy_version": old.policy_version + 1}),
                              expected_version=old.policy_version, actor_id="test-admin")
        return {"evidence_ids": [e["id"] for e in payload["evidence"]],
                "recommendation_ids": [], "conflict_evidence_ids": []}
    request = DiagnoseRequest(equipment_id="EQ-ROBOT-001", symptom="模拟异常")
    if revoke:
        with pytest.raises(ResourceUnavailable):
            diagnose(business, store, token, request, mode="deepseek", diagnosis_transport=transport)
    else:
        result = diagnose(business, store, token, request, mode="deepseek", diagnosis_transport=transport)
        assert len(result.evidence) == 8


@pytest.mark.parametrize("variant", ["valid", "missing_safety", "wrong_version", "forbidden"])
def test_sop_requires_authorized_reviewed_version_and_safety(system, variant):
    business, store, token = system
    source = (PROJECT_ROOT / "data/raw_docs/sops/escalation.txt").read_bytes()
    content = source.decode("utf-8")
    digest = hashlib.sha256(source).hexdigest()
    if variant == "missing_safety":
        content = content.replace("本流程不提供报警复位动作，不授权绕过联锁，不替代现场安全规程。", "")
    if variant == "wrong_version":
        digest = "unreviewed-version"
    policies = business.stores["document"]
    old = policies.get_many(["SOP-ESCALATION"]).get("SOP-ESCALATION")
    version = old.policy_version if old else 0
    policies.save(ResourcePolicy(
        resource_id="SOP-ESCALATION", department_id="B" if variant == "forbidden" else "A",
        visibility="department", classification=1, status="active",
        policy_version=version + 1, content_version=digest), expected_version=version, actor_id="test-admin")
    store.upsert(ids=["sop-chunk"], documents=[content], metadatas=[{
        "chunk_id": "sop-chunk", "document_id": "SOP-ESCALATION", "source_file": "escalation.txt",
        "policy_version": version + 1, "content_version": digest, "equipment_id": "ALL-SIMULATED"}])
    result = diagnose(business, store, token, DiagnoseRequest(
        equipment_id="EQ-ROBOT-001", symptom="请介绍维修过程"))
    if variant == "valid":
        assert len(result.recommendation_details) == 1
        recommendation = result.recommendation_details[0]
        assert set(recommendation.evidence_ids) <= {e.evidence_id for e in result.evidence}
        assert "人工" in recommendation.text
        assert not result.grounded  # This is escalation, not a diagnosed root cause.
    else:
        assert result.recommendation_details == [] and result.suggestions == []
