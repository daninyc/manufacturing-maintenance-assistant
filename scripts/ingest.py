"""批量导入独立 Day 2 语义集合；每次保留独立验收报告。"""
import json
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4

from app.core.config import CHROMA_PATH, DAY2_COLLECTION, PROJECT_ROOT
from app.ingestion.indexer import index_document
from app.retrieval.vector_store import LocalChromaStore


def main() -> None:
    start = perf_counter()
    raw = PROJECT_ROOT / "data/raw_docs"
    store = LocalChromaStore(CHROMA_PATH, DAY2_COLLECTION, semantic=True)
    before_count = store.collection.count()
    results = []
    for item in json.loads((raw / "manifest.json").read_text(encoding="utf-8")):
        metadata = {key: item[key] for key in
                    ("document_id", "equipment_type", "version", "source_url", "equipment_id",
                     "source_type", "published_at")}
        try:
            count = index_document(raw / item["file"], store, **metadata)
            results.append({"file": item["file"], "chunks": count, "error": None})
        except (ValueError, OSError) as exc:
            results.append({"file": item["file"], "chunks": 0, "error": str(exc)})
    report = {"collection": DAY2_COLLECTION, "before_count": before_count,
              "documents": len(results), "chunks": sum(row["chunks"] for row in results),
              "failures": sum(row["error"] is not None for row in results),
              "collection_count": store.collection.count(),
              "seconds": round(perf_counter() - start, 3), "files": results}
    # 独立命名保留重复导入的前后证据，不覆盖用户已有验收记录。
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    path = PROJECT_ROOT / f"docs/evidence/day2/ingestion-{run_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    report["report_path"] = str(path)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if report["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
