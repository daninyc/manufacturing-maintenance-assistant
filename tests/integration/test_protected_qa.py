import os

import pytest

from app.auth.sessions import AuthenticationError, SessionStore
from app.ingestion.publication import publish_document
from app.retrieval.vector_store import LocalChromaStore
from app.schemas.qa import AskRequest
from app.security.authorization import ResourcePolicy
from app.security.policies import PolicyStore
from app.services.evidence import EvidenceQuote, EvidenceSelection
from app.services.protected_qa import authorized_answer


@pytest.fixture
def context(tmp_path):
    sessions = SessionStore(tmp_path / "access.sqlite3")
    policies = PolicyStore(sessions)
    policies.initialize()
    admin = sessions.create_user("admin", "test-only-admin-password", role="admin",
                                  department_id="ADMIN", clearance=2)
    reader = sessions.create_user("alice", "test-only-alice-password", role="employee",
                                   department_id="A", clearance=1)
    store = LocalChromaStore(tmp_path / "chroma", "authorized_test")
    return sessions, policies, store, admin, reader, tmp_path


def spec(resource="DOC-A", department="A", **changes):
    return ResourcePolicy(**({
        "resource_id": resource, "department_id": department, "visibility": "department",
        "classification": 1, "status": "draft", "content_version": "v1",
        "policy_version": 1, "external_processing_allowed": True} | changes))


def publish(context, content, proposed=None):
    sessions, policies, store, _, _, path = context
    proposed = proposed or spec()
    document = path / (proposed.resource_id + ".txt")
    document.write_text(content, encoding="utf-8")
    token = sessions.login("admin", "test-only-admin-password")
    return publish_document(document, proposed, store, policies, sessions, token,
                            expected_version=0)


def choose(question, chunks):
    return EvidenceSelection(supported=True, quotes=[
        EvidenceQuote(chunk_id=chunks[0].metadata["chunk_id"], excerpt=chunks[0].text)])


def answer(context, **kwargs):
    sessions, policies, store, _, _, _ = context
    token = sessions.login("alice", "test-only-alice-password")
    return authorized_answer(store, policies, sessions, token,
                             AskRequest(question="维护说明", top_k=1), selector=choose,
                             max_distance=2, **kwargs)


def test_publish_inherits_policy_and_prevents_cross_department(context):
    active = publish(context, "READABLE_A")
    publish(context, "SIM_SECRET_B", spec("DOC-B", "B"))
    result = answer(context)
    assert result.grounded
    assert "READABLE_A" in result.answer
    assert "SIM_SECRET_B" not in result.model_dump_json()
    assert result.citations[0].document_id == "DOC-A"
    assert result.citations[0].policy_version == active.policy_version
    assert result.citations[0].content_version == active.content_version


def test_real_bge_retrieval_respects_department_and_withdrawal(context):
    sessions, policies, _, admin, reader, path = context
    semantic_store = LocalChromaStore(path / "semantic-chroma", "permission_bge", semantic=True)
    semantic_context = (sessions, policies, semantic_store, admin, reader, path)
    active = publish(semantic_context, "模拟设备维护说明：检查维护记录。READABLE_A")
    publish(semantic_context, "模拟设备维护说明：内部工艺参数。SIM_SECRET_B", spec("DOC-B", "B"))
    result = answer(semantic_context)
    assert result.grounded and "READABLE_A" in result.answer
    assert "SIM_SECRET_B" not in result.model_dump_json()
    policies.save(ResourcePolicy.model_validate(active.model_dump() | {
        "status": "disabled", "policy_version": active.policy_version + 1}),
        expected_version=active.policy_version, actor_id=admin.user_id)
    assert semantic_store.collection.count() == 2
    assert not answer(semantic_context).grounded


@pytest.mark.skipif(os.getenv("RUN_LIVE_DEEPSEEK") != "1", reason="Explicit live-model opt-in required")
def test_live_deepseek_with_bge_and_authorized_simulated_documents(context):
    sessions, policies, _, admin, reader, path = context
    store = LocalChromaStore(path / "live-chroma", "live_permission_bge", semantic=True)
    live_context = (sessions, policies, store, admin, reader, path)
    active = publish(live_context, "模拟设备点检要求：每日检查维护记录是否完整。")
    publish(live_context, "模拟设备点检要求：SIM_SECRET_B_8492。", spec("DOC-B", "B"))
    token = sessions.login("alice", "test-only-alice-password")
    result = authorized_answer(store, policies, sessions, token,
        AskRequest(question="模拟设备每日点检需要检查什么？", top_k=1), mode="deepseek")
    assert result.grounded, "Live model did not return supported evidence"
    assert result.citations and all(c.document_id == "DOC-A" for c in result.citations)
    assert "维护记录" in result.answer
    assert "SIM_SECRET_B_8492" not in result.model_dump_json()
    assert all(c.policy_version == active.policy_version for c in result.citations)


def test_no_authorized_candidates_never_calls_selector(context):
    publish(context, "SIM_SECRET_B", spec("DOC-B", "B"))
    sessions, policies, store, _, _, _ = context
    def forbidden(*args):
        pytest.fail("Model was called without authorized evidence")
    result = authorized_answer(store, policies, sessions,
                               sessions.login("alice", "test-only-alice-password"),
                               AskRequest(question="anything"), selector=forbidden)
    assert not result.grounded


def test_external_processing_disabled_never_calls_model(context):
    publish(context, "LOCAL_ONLY", spec(external_processing_allowed=False))
    assert not answer(context, mode="deepseek").grounded


def test_withdrawn_policy_filters_residual_vectors(context):
    active = publish(context, "SIM_SECRET_WITHDRAWN")
    _, policies, store, admin, _, _ = context
    disabled = ResourcePolicy.model_validate(active.model_dump() | {
        "status": "disabled", "policy_version": active.policy_version + 1})
    policies.save(disabled, expected_version=active.policy_version, actor_id=admin.user_id)
    assert store.collection.count() == 1
    assert not answer(context).grounded


def test_revoke_during_selection_never_publishes(context):
    publish(context, "READABLE_BEFORE_REVOKE")
    sessions, policies, store, _, reader, _ = context
    token = sessions.login("alice", "test-only-alice-password")
    def revoke(question, chunks):
        sessions.change_access(reader.user_id, role="employee", department_id="B",
                               clearance=0, active=True)
        return choose(question, chunks)
    with pytest.raises(AuthenticationError):
        authorized_answer(store, policies, sessions, token,
                          AskRequest(question="text"), selector=revoke, max_distance=2)


def test_unknown_output_id_refuses_entire_response(context):
    publish(context, "READABLE")
    sessions, policies, store, _, _, _ = context
    def forged(question, chunks):
        return EvidenceSelection(supported=True, quotes=[
            EvidenceQuote(chunk_id="OTHER_REQUEST_ID", excerpt="SECRET")])
    result = authorized_answer(store, policies, sessions,
                               sessions.login("alice", "test-only-alice-password"),
                               AskRequest(question="text"), selector=forged, max_distance=2)
    assert not result.grounded
    assert result.citations == []


def test_index_failure_leaves_document_inaccessible(context):
    sessions, policies, _, _, _, path = context
    document = path / "broken.txt"
    document.write_text("VALID TEXT", encoding="utf-8")
    class Broken:
        def upsert(self, **kwargs):
            raise RuntimeError("index failure")
    with pytest.raises(RuntimeError):
        publish_document(document, spec(), Broken(), policies, sessions,
                         sessions.login("admin", "test-only-admin-password"),
                         expected_version=0)
    assert policies.get_many(["DOC-A"])["DOC-A"].status == "failed"


def test_non_admin_cannot_publish(context):
    sessions, policies, store, _, _, path = context
    document = path / "forged.txt"
    document.write_text("FORGED", encoding="utf-8")
    with pytest.raises(PermissionError):
        publish_document(document, spec(), store, policies, sessions,
                         sessions.login("alice", "test-only-alice-password"),
                         expected_version=0)
    assert policies.get_many(["DOC-A"]) == {}


def test_empty_allowlist_returns_nothing(context):
    publish(context, "READABLE")
    store = context[2]
    assert store.query("text", 3, document_ids=[])["documents"] == [[]]


def test_publication_hash_and_text_use_same_snapshot(context, monkeypatch):
    import hashlib

    from app.ingestion import publication

    original = publication.load_documents
    def replace_file(path, **kwargs):
        path.write_text("REPLACED_CONTENT", encoding="utf-8")
        return original(path, **kwargs)
    monkeypatch.setattr(publication, "load_documents", replace_file)
    active = publish(context, "ORIGINAL_CONTENT")
    assert active.content_version == hashlib.sha256(b"ORIGINAL_CONTENT").hexdigest()
    assert context[2].collection.get(include=["documents"])["documents"] == ["ORIGINAL_CONTENT"]


@pytest.mark.parametrize("stage", ["indexing", "active"])
def test_publication_rechecks_admin_in_policy_transaction(context, monkeypatch, stage):
    sessions, policies, store, admin, _, _ = context
    original = policies.save
    def revoke_before_write(policy, **kwargs):
        if policy.status == stage:
            sessions.change_access(admin.user_id, role="employee", department_id="ADMIN",
                                   clearance=2, active=True)
        return original(policy, **kwargs)
    monkeypatch.setattr(policies, "save", revoke_before_write)
    with pytest.raises(AuthenticationError):
        publish(context, "MUST_NOT_PUBLISH")
    labels = policies.get_many(["DOC-A"])
    if stage == "indexing":
        assert labels == {}
        assert store.collection.count() == 0
    else:
        assert labels["DOC-A"].status == "failed"
    assert not answer(context).grounded

def test_untrusted_retriever_result_is_filtered_before_selector(context):
    publish(context, "READABLE_A")
    publish(context, "SIM_SECRET_B", spec("DOC-B", "B"))
    sessions, policies, store, _, _, _ = context
    class LeakingIndex:
        semantic = False
        def query(self, *args, **kwargs):
            # Simulate an index bug that ignores the prefilter.
            data = store.collection.get(include=["documents", "metadatas"])
            return {"documents": [data["documents"]], "metadatas": [data["metadatas"]],
                    "distances": [[0.1] * len(data["ids"])]}
    def inspect(question, chunks):
        assert all("SIM_SECRET_B" not in c.text for c in chunks)
        return choose(question, chunks)
    result = authorized_answer(LeakingIndex(), policies, sessions,
                               sessions.login("alice", "test-only-alice-password"),
                               AskRequest(question="anything", top_k=1),
                               selector=inspect, max_distance=2)
    assert result.grounded


def test_http_citation_rechecks_policy(context):
    from fastapi.testclient import TestClient

    from app.api.server import create_app

    active = publish(context, "READABLE_A")
    sessions, policies, store, admin, _, _ = context
    app = create_app(sessions.path)
    app.state.vector_store = store
    client = TestClient(app)
    auth = {"Authorization": "Bearer " + sessions.login("alice", "test-only-alice-password")}
    chunk_id = store.collection.get()["ids"][0]
    url = f"/api/v1/documents/DOC-A/chunks/{chunk_id}"
    assert client.get(url).status_code == 401
    assert client.get(url, headers=auth).json()["excerpt"] == "READABLE_A"
    assert client.get(f"/api/v1/documents/OTHER/chunks/{chunk_id}", headers=auth).status_code == 404
    disabled = ResourcePolicy.model_validate(active.model_dump() | {
        "status": "disabled", "policy_version": active.policy_version + 1})
    policies.save(disabled, expected_version=active.policy_version, actor_id=admin.user_id)
    assert client.get(url, headers=auth).status_code == 404


def test_http_ask_rejects_unauthenticated_and_forged_identity(context):
    from fastapi.testclient import TestClient

    from app.api.server import create_app

    sessions = context[0]
    app = create_app(sessions.path)
    client = TestClient(app)
    assert client.post("/api/v1/ask", json={"question": "anything"}).status_code == 401
    assert app.state.vector_store is None
    auth = {"Authorization": "Bearer " + sessions.login("alice", "test-only-alice-password")}
    response = client.post("/api/v1/ask", headers=auth, json={
        "question": "anything", "role": "admin", "department_id": "B"})
    assert response.status_code == 422
    assert app.state.vector_store is None
