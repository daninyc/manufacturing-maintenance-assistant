"""保存真实检索及引用；默认五题、可选扩展集，不宣称通用准确率。"""
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from app.core.config import CHROMA_PATH, DAY2_COLLECTION, MAX_DISTANCE, PROJECT_ROOT
from app.ingestion.loaders import load_documents
from app.retrieval.vector_store import LocalChromaStore
from app.schemas.qa import AskRequest
from app.services.qa_service import _answer_baseline, answer_question


def check_answer(case: dict, response, trace: dict, sources: dict) -> dict:
    """自动检查来源/数值绑定；条件和否定语义另标人工复核，不用禁词误判。"""
    checks = []
    for citation in response.citations:
        path = sources.get(citation.source_file)
        page = citation.page or 1
        valid = False
        if path:
            pages = load_documents(path)
            valid = 1 <= page <= len(pages) and citation.excerpt in pages[page - 1].text
        checks.append(valid)
    facts_valid = True
    for fact in case.get("facts", []):
        matching = [c.excerpt for c in response.citations
                    if fact["source"].lower() in c.source_file.lower()]
        pattern = r"(?<![\d.])" + re.escape(str(fact["value"])) + r"\s*" + re.escape(fact["unit"])
        facts_valid &= any(re.search(pattern, text, re.IGNORECASE) for text in matching)
    if case.get("expect_refusal"):
        behavior_valid = (not response.grounded and not response.citations
                          and trace.get("reason") in {"NO_RETRIEVAL_HITS", "BELOW_THRESHOLD",
                                                     "MODEL_UNSUPPORTED", "LOCAL_UNSUPPORTED"})
    else:
        behavior_valid = response.grounded and bool(response.citations) and facts_valid
    return {"passed": bool(behavior_valid and all(checks)), "citation_check": all(checks),
            "facts_check": bool(facts_valid), "manual_review_required": case.get("manual_review", False)}


def run(mode: str, baseline: bool = False, *, extended: bool = False,
        cases_path: Path | None = None) -> dict:
    store = LocalChromaStore(CHROMA_PATH, DAY2_COLLECTION, semantic=True)
    cases = json.loads((cases_path or PROJECT_ROOT / "data/eval/day2_regression_questions.json")
                       .read_text(encoding="utf-8"))
    if not extended:
        cases = cases[:5]
    manifest = json.loads((PROJECT_ROOT / "data/raw_docs/manifest.json").read_text(encoding="utf-8"))
    sources = {row["file"].split("/")[-1]: PROJECT_ROOT / "data/raw_docs" / row["file"]
               for row in manifest}
    rows = []
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    path = PROJECT_ROOT / f"docs/evidence/day2/smoke-{'before_gate' if baseline else mode}-{run_id}.json"
    report = {"run_id": run_id, "mode": "before_gate" if baseline else mode,
              "total": len(cases), "passed": 0, "cases": rows, "report_path": str(path)}
    for case in cases:
        start = perf_counter()
        request = AskRequest(question=case["question"], top_k=6)
        trace = {}
        row = {"id": case["id"], "kind": case["kind"], "query": request.question,
               "top_k": request.top_k, "max_distance": MAX_DISTANCE, "passed": False,
               "trace": trace}
        try:
            response = (_answer_baseline(store, request) if baseline else
                        answer_question(store, request, mode=mode, max_distance=MAX_DISTANCE, trace=trace))
            row.update(response=response.model_dump(), **check_answer(case, response, trace, sources))
        except Exception as exc:  # noqa: BLE001 - 验收边界逐题记录失败，不掩盖失败退出码
            # 验收需要逐题继续；不写 str(exc)，避免第三方异常包含请求头等敏感内容。
            row.update(error_type=type(exc).__name__, reason=trace.get("reason") or "PIPELINE_ERROR")
        row["seconds"] = round(perf_counter() - start, 3)
        rows.append(row)
        report["passed"] = sum(item["passed"] for item in rows)
        report["completed"] = len(rows)
        # 每题更新独立文件，中途故障仍保留已完成记录；历史报告不覆盖。
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{row['id']}: passed={row['passed']} reason={trace.get('reason')}", flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["local", "deepseek"], default="local")
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--extended", action="store_true", help="执行全部扩展题")
    args = parser.parse_args()
    report = run(args.mode, args.baseline, extended=args.extended)
    for row in report["cases"]:
        print(row["id"], row["passed"], row.get("response", {}).get("answer", row.get("error_type")))
    print(f"passed={report['passed']}/{report['total']}; mode={report['mode']}")
    print(report["report_path"])
    if report["passed"] != report["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
