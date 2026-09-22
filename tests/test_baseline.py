from pathlib import Path

import pytest
from pydantic import ValidationError

from app.ingestion.indexer import index_txt
from app.ingestion.splitter import split_text
from app.retrieval.vector_store import LocalChromaStore
from app.schemas.qa import AskRequest
from app.services.qa_service import answer_question


def test_splitter_preserves_overlap_and_rejects_invalid_values() -> None:
    chunks = split_text("abcdefghij", "doc", chunk_size=6, overlap=2)
    assert [chunk.text for chunk in chunks] == ["abcdef", "efghij"]
    assert chunks[1].chunk_id == "doc::chunk-0001"
    with pytest.raises(ValueError):
        split_text("abc", "doc", chunk_size=3, overlap=3)


def test_request_contract_rejects_invalid_top_k() -> None:
    with pytest.raises(ValidationError):
        AskRequest(question="test", top_k=11)


def test_baseline_returns_traceable_answer(tmp_path: Path) -> None:
    document = tmp_path / "demo.txt"
    document.write_text("例行维护窗口为每周三上午十点。", encoding="utf-8")
    store = LocalChromaStore(tmp_path / "chroma", "integration_test")
    no_evidence = answer_question(store, AskRequest(question="未知问题", top_k=1))
    assert no_evidence.grounded is False

    index_txt(document, store)

    response = answer_question(store, AskRequest(question="维护窗口是什么时间？", top_k=1))

    assert response.grounded is True
    assert response.citations[0].source_file == "demo.txt"
    assert "每周三上午十点" in response.answer
