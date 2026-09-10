import json
import re
from pathlib import Path

from app.core.config import PROJECT_ROOT
from app.ingestion.indexer import index_document
from app.ingestion.loaders import load_documents
from app.retrieval.vector_store import LocalChromaStore

RAW = PROJECT_ROOT / "data/raw_docs"


def test_official_pdfs_load_with_real_pages() -> None:
    for name, model in [("ur3e_official.pdf", "UR3e"), ("irb120_official.pdf", "IRB 120")]:
        path = RAW / "manuals" / name
        assert path.exists(), "先运行 python -m scripts.fetch_sources 下载官方 PDF"
        documents = load_documents(path, equipment_type="robot", version="source-snapshot")
        assert model in " ".join(doc.text for doc in documents)
        assert [doc.metadata["page"] for doc in documents] == list(range(1, len(documents) + 1))
        assert all(doc.metadata["source_file"] == name for doc in documents)


def test_question_evidence_coverage() -> None:
    """验证资料覆盖，不能据此宣称模型问答或拒答已经通过。"""
    questions = json.loads((PROJECT_ROOT / "data/eval/day2_questions.json").read_text(encoding="utf-8"))
    for question in questions:
        for evidence in question["evidence"]:
            text = "\n".join(doc.text for doc in load_documents(RAW / evidence["file"]))
            assert all(term in text for term in evidence["terms"]), question["id"]
        if question["kind"] == "no_answer":
            texts = "\n".join(doc.text for path in RAW.rglob("*.txt") for doc in load_documents(path))
            assert not re.search(question["absent_pattern"], texts)


def test_pdf_index_is_repeatable_and_keeps_pages(tmp_path: Path) -> None:
    store = LocalChromaStore(tmp_path / "chroma", "day2_test")
    path = RAW / "manuals/ur3e_official.pdf"
    first = index_document(path, store, document_id="UR3E", version="v1")
    second = index_document(path, store, document_id="UR3E", version="v1")
    assert first == second == store.collection.count()
    result = store.query("UR3e payload", 1)
    assert result["metadatas"][0][0]["page"] == 1
    assert result["metadatas"][0][0]["version"] == "v1"


def test_shorter_document_removes_only_its_old_chunks(tmp_path: Path) -> None:
    store = LocalChromaStore(tmp_path / "chroma", "shorten_test")
    first, other = tmp_path / "first.txt", tmp_path / "other.txt"
    first.write_text("测试文档" * 500, encoding="utf-8")
    other.write_text("另一份文档应保留", encoding="utf-8")
    index_document(first, store)
    index_document(other, store)
    first.write_text("缩短文档", encoding="utf-8")
    index_document(first, store)
    assert store.collection.count() == 2
    assert store.collection.get(where={"document_id": "other"})["documents"] == ["另一份文档应保留"]
