from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_page_can_answer_comparison():
    path = Path(__file__).resolve().parents[2] / "ui/streamlit_app.py"
    app = AppTest.from_file(str(path), default_timeout=30).run()
    assert not app.exception
    app.button[0].click().run()
    assert not app.exception
    response = app.session_state["day2_response"]
    assert response.grounded
    assert len({citation.source_file for citation in response.citations}) == 2
