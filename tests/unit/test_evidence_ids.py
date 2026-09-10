import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.retrieval.retriever import RetrievedChunk
from app.services.evidence import (
    EvidenceError,
    SelectedEvidenceIds,
    build_candidates,
    resolve_selection,
    select_with_deepseek,
)


def chunk(text, chunk_id="doc::page-1::chunk-0"):
    return RetrievedChunk(text, {"chunk_id": chunk_id, "source_file": "ur3e_official.pdf"}, 0.2)


def test_pdf_newline_is_returned_unchanged():
    text = "Boasting a 3 kg payload and a 500 mm\nreach."
    candidates = build_candidates([chunk(text)])
    result = resolve_selection(SelectedEvidenceIds(supported=True, evidence_ids=["E001"]), candidates)
    assert result.quotes[0].excerpt == text


def test_nonadjacent_sentences_remain_separate():
    text = "最大负载 3 kg。中间一段说明。不得把负载改为 5 kg。"
    candidates = build_candidates([chunk(text)])
    result = resolve_selection(SelectedEvidenceIds(supported=True, evidence_ids=["E001", "E003"]), candidates)
    assert len(result.quotes) == 2
    assert all(quote.excerpt in text for quote in result.quotes)
    assert "中间一段说明" not in result.quotes[0].excerpt


def test_candidate_bounds_preserve_decimals_and_condition():
    text = "Repeatability 0.03 mm. Only under rated conditions.\n" + ("长段资料" * 200)
    candidates = build_candidates([chunk(text)])
    assert all(0 < len(q.excerpt) <= 240 and q.excerpt in text for q in candidates.values())
    assert candidates["E001"].excerpt == "Repeatability 0.03 mm."
    assert candidates["E002"].excerpt == "Only under rated conditions."


@pytest.mark.parametrize("ids,reason", [([], "EMPTY_SELECTION"),
                                      (["E999"], "UNKNOWN_EVIDENCE_ID"),
                                      (["E001", "E999"], "UNKNOWN_EVIDENCE_ID")])
def test_invalid_selection_is_not_partially_accepted(ids, reason):
    candidates = build_candidates([chunk("原文。")])
    with pytest.raises(EvidenceError, match=reason):
        resolve_selection(SelectedEvidenceIds(supported=True, evidence_ids=ids), candidates)


def test_duplicate_ids_are_removed():
    candidates = build_candidates([chunk("原文。")])
    result = resolve_selection(SelectedEvidenceIds(supported=True, evidence_ids=["E001", "E001"]), candidates)
    assert len(result.quotes) == 1


def test_old_model_response_is_rejected():
    with pytest.raises(ValidationError):
        SelectedEvidenceIds.model_validate({"supported": True, "quotes": [{"excerpt": "fake"}]})


def test_online_contract_resolves_ids_not_model_text(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-only")
    captured = {}
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return json.dumps({"choices": [{"message": {"content":
                '{"supported": true, "evidence_ids": ["E001"]}'}}]}).encode()
    def fake_urlopen(request, timeout):
        captured.update(json.loads(request.data))
        return Response()
    monkeypatch.setattr("app.services.evidence.urlopen", fake_urlopen)
    trace = {}
    result = select_with_deepseek("UR3e 半径", [chunk("500 mm\nreach.")], trace=trace)
    assert result.quotes[0].excerpt == "500 mm\nreach."
    context = json.loads(captured["messages"][1]["content"])["context"]
    assert context[0]["evidence_id"] == "E001"
    assert trace["model_selection"]["evidence_ids"] == ["E001"]


def test_report_continues_on_error_and_preserves_runs(tmp_path, monkeypatch):
    from scripts import run_day2_smoke as runner
    (tmp_path / "data/raw_docs").mkdir(parents=True)
    (tmp_path / "data/raw_docs/manifest.json").write_text("[]", encoding="utf-8")
    (tmp_path / "docs/evidence/day2").mkdir(parents=True)
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(json.dumps([
        {"id": "A", "kind": "no_answer", "question": "one", "expect_refusal": True},
        {"id": "B", "kind": "no_answer", "question": "two", "expect_refusal": True},
    ]), encoding="utf-8")
    monkeypatch.setattr(runner, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runner, "LocalChromaStore", lambda *args, **kwargs: SimpleNamespace())
    def fail(*args, **kwargs):
        kwargs["trace"]["reason"] = "MODEL_ERROR"
        raise RuntimeError("sensitive remote error must not be logged")
    monkeypatch.setattr(runner, "answer_question", fail)
    first = runner.run("deepseek", cases_path=cases_path)
    second = runner.run("deepseek", cases_path=cases_path)
    assert first["completed"] == 2 and first["passed"] == 0
    assert first["report_path"] != second["report_path"]
    assert all(row["reason"] == "MODEL_ERROR" for row in first["cases"])
    assert "sensitive remote" not in json.dumps(first)


def test_conflict_checker_accepts_correction_not_forbidden_word(tmp_path):
    from app.schemas.qa import AskResponse, Citation
    from scripts.run_day2_smoke import check_answer
    path = tmp_path / "ur3e_summary.txt"
    text = "官方规格：3 kg。"
    path.write_text(text, encoding="utf-8")
    case = {"facts": [{"source": "ur3e", "value": 3, "unit": "kg"}], "manual_review": True}
    response = AskResponse(answer="不是 5 kg，资料给出 3 kg。", grounded=True, request_id="test",
                           citations=[Citation(source_file=path.name, chunk_id="x", page=1, excerpt=text)])
    result = check_answer(case, response, {}, {path.name: path})
    assert result["passed"]
    assert result["manual_review_required"]


def test_fact_checker_does_not_swap_equipment(tmp_path):
    from app.schemas.qa import AskResponse, Citation
    from scripts.run_day2_smoke import check_answer
    path = tmp_path / "ur5e_summary.txt"
    text = "负载 3 kg。"
    path.write_text(text, encoding="utf-8")
    response = AskResponse(answer=text, grounded=True, request_id="test",
                           citations=[Citation(source_file=path.name, chunk_id="x", excerpt=text)])
    result = check_answer({"facts": [{"source": "ur3e", "value": 3, "unit": "kg"}]},
                          response, {}, {path.name: path})
    assert not result["passed"]
