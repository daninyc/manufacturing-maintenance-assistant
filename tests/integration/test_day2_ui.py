from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_original_comparison_service_baseline():
    from app.core.config import CHROMA_PATH, DAY2_COLLECTION, MAX_DISTANCE
    from app.retrieval.vector_store import LocalChromaStore
    from app.schemas.qa import AskRequest
    from app.services.qa_service import answer_question

    store = LocalChromaStore(CHROMA_PATH, DAY2_COLLECTION, semantic=True)
    response = answer_question(store, AskRequest(
        question="比较 UR3e 与 UR5e 的负载和工作半径。", top_k=6), mode="local", max_distance=MAX_DISTANCE)
    assert response.grounded
    assert len({citation.source_file for citation in response.citations}) == 2


def test_page_requires_config_before_showing_question(monkeypatch):
    monkeypatch.delenv("MAINTENANCE_API_URL", raising=False)
    path = Path(__file__).resolve().parents[2] / "ui/streamlit_app.py"
    app = AppTest.from_file(str(path), default_timeout=30).run()
    assert not app.exception
    assert not app.button and app.info


def test_page_login_answer_and_revoked_citation(monkeypatch):
    from ui.api_transport import ApiError

    monkeypatch.setenv("MAINTENANCE_API_URL", "https://example.com")
    revoked = False
    calls = []
    citation = {"document_id": "DOC-A", "chunk_id": "chunk-A", "source_file": "simulation.txt",
                "policy_version": 1, "content_version": "v1", "excerpt": "SIM_VISIBLE_A"}
    def fake_api(server, method, segments, *, token=None, payload=None):
        calls.append(segments)
        if segments == ["auth", "login"]:
            assert payload["username"] == "alice"
            return {"access_token": "test-only-session-token"}
        assert token == "test-only-session-token"
        if segments == ["me"]:
            return {"user_id": "alice"}
        if segments == ["ask"]:
            return {"answer": "SIM_VISIBLE_A", "citations": [citation], "grounded": True, "request_id": "test"}
        if segments == ["documents", "DOC-A", "chunks", "chunk-A"]:
            if revoked:
                raise ApiError(404)
            return citation
        raise AssertionError("Unexpected API request")
    monkeypatch.setattr("ui.api_transport.call_api", fake_api)
    path = Path(__file__).resolve().parents[2] / "ui/streamlit_app.py"
    app = AppTest.from_file(str(path), default_timeout=30).run()
    assert len(app.text_input) == 2 and calls == []
    app.text_input[0].set_value("alice")
    app.text_input[1].set_value("test-only-password")
    app.button[0].click().run()
    assert not app.exception
    next(button for button in app.button if button.label == "提问").click().run()
    assert not app.exception
    response = app.session_state["day2_response"]
    assert response["grounded"]
    assert ["documents", "DOC-A", "chunks", "chunk-A"] in calls
    revoked = True
    app.run()
    assert not app.exception and app.warning
    assert "day2_response" not in app.session_state
    assert not any("SIM_VISIBLE_A" in item.value for item in app.markdown)
