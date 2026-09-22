import json
from types import SimpleNamespace

from scripts import ingest


def test_ingestion_preserves_reports_and_records_counts(tmp_path, monkeypatch):
    raw = tmp_path / "data/raw_docs"
    raw.mkdir(parents=True)
    (raw / "manifest.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(ingest, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(ingest, "LocalChromaStore", lambda *args, **kwargs:
                        SimpleNamespace(collection=SimpleNamespace(count=lambda: 31)))
    ingest.main()
    ingest.main()
    paths = list((tmp_path / "docs/evidence/day2").glob("ingestion-*.json"))
    assert len(paths) == 2
    for path in paths:
        report = json.loads(path.read_text(encoding="utf-8"))
        assert report["before_count"] == report["collection_count"] == 31
        assert report["failures"] == 0
        assert report["report_path"] == str(path)
