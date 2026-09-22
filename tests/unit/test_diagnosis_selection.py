import pytest

from app.schemas.diagnosis import Evidence, Recommendation
from app.services.diagnosis_selection import choose_diagnosis


def inputs():
    evidence = [Evidence(evidence_id=str(i), source_type=kind, summary="模拟证据", source_ref=str(i))
                for i, kind in enumerate(("knowledge", "alarm", "maintenance"))]
    recommendation = Recommendation(recommendation_id="r", text="模拟升级",
                                    evidence_ids=["0", "1"], applicable_conditions=["模拟条件"])
    return evidence, [recommendation]


def test_three_source_selection_keeps_server_text():
    evidence, recommendations = inputs()
    def transport(payload):
        assert {e["source_type"] for e in payload["evidence"]} == {"knowledge", "alarm", "maintenance"}
        return {"evidence_ids": [e["id"] for e in payload["evidence"]],
                "recommendation_ids": [payload["recommendations"][0]["id"]], "conflict_evidence_ids": []}
    selected, suggestions, conflicts = choose_diagnosis("模拟问题", evidence, recommendations, transport=transport)
    assert selected == evidence and suggestions == recommendations and conflicts == []


@pytest.mark.parametrize("bad", ["unknown", "missing_support", "single_conflict", "extra_text"])
def test_invalid_selection_rejected(bad):
    def transport(payload):
        ids = [e["id"] for e in payload["evidence"]]
        output = {"evidence_ids": ids, "recommendation_ids": [], "conflict_evidence_ids": []}
        if bad == "unknown":
            output["evidence_ids"].append("other-request:E0")
        elif bad == "missing_support":
            output["evidence_ids"] = ids[1:]
            output["recommendation_ids"] = [payload["recommendations"][0]["id"]]
        elif bad == "single_conflict":
            output["conflict_evidence_ids"] = [ids[0]]
        else:
            output["repair_instruction"] = "untrusted"
        return output
    with pytest.raises((RuntimeError, ValueError)):
        choose_diagnosis("模拟问题", *inputs(), transport=transport)


def test_conflicts_suppress_suggestions_and_are_only_suspected():
    def transport(payload):
        ids = [e["id"] for e in payload["evidence"]]
        return {"evidence_ids": ids, "recommendation_ids": [payload["recommendations"][0]["id"]],
                "conflict_evidence_ids": ids[:2]}
    selected, suggestions, conflicts = choose_diagnosis("模拟问题", *inputs(), transport=transport)
    assert len(selected) == 3 and suggestions == [] and conflicts == ["0", "1"]
