import argparse
import json
from pathlib import Path

from app.core.config import CHROMA_COLLECTION, CHROMA_PATH, PROJECT_ROOT, TOP_K
from app.ingestion.indexer import index_document
from app.retrieval.vector_store import LocalChromaStore
from app.schemas.qa import AskRequest
from app.services.qa_service import answer_question


def run_baseline(document: Path, question: str, reset: bool = False) -> dict:
    store = LocalChromaStore(CHROMA_PATH, CHROMA_COLLECTION)
    if reset:
        store.reset()
    chunk_count = index_document(document, store)
    response = answer_question(store, AskRequest(question=question, top_k=TOP_K))
    return {"indexed_chunks": chunk_count, **response.model_dump(mode="json")}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Day 1 RAG baseline")
    parser.add_argument(
        "--document",
        type=Path,
        default=PROJECT_ROOT / "data/raw_docs/baseline_demo.txt",
    )
    parser.add_argument("--question", default="维护窗口是什么时间？")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rendered = json.dumps(
        run_baseline(args.document, args.question, args.reset),
        ensure_ascii=False,
        indent=2,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
