import re
from uuid import uuid4

from app.core.config import MAX_DISTANCE
from app.retrieval.retriever import retrieve
from app.retrieval.vector_store import LocalChromaStore
from app.schemas.qa import AskRequest, AskResponse, Citation


def _answer_baseline(store: LocalChromaStore, request: AskRequest) -> AskResponse:
    """检索后生成带真实引用的基线回答；无命中时直接拒答。"""
    request_id = str(uuid4())
    chunks = retrieve(store, request.question, request.top_k)
    if not chunks:
        return AskResponse(
            answer="现有资料不足，无法回答；请补充文档或转人工确认。",
            citations=[],
            grounded=False,
            request_id=request_id,
        )

    # 回答文本可以换模型，但引用必须由检索结果的 metadata 构造。
    citations = [
        Citation(
            source_file=str(chunk.metadata["source_file"]),
            page=chunk.metadata.get("page"),
            source_url=chunk.metadata.get("source_url") or None,
            chunk_id=str(chunk.metadata["chunk_id"]),
            excerpt=chunk.text[:240],
            distance=round(chunk.distance, 6),
        )
        for chunk in chunks
    ]
    # ponytail: Day 1 只证明链路可运行；需要自然语言生成时再接入模型 API。
    answer = f"基线测试替身根据首条命中文本回答：{chunks[0].text}"
    return AskResponse(answer=answer, citations=citations, grounded=True, request_id=request_id)


def answer_question(store: LocalChromaStore, request: AskRequest, *,
                    mode: str = "local", max_distance: float = MAX_DISTANCE,
                    trace: dict | None = None) -> AskResponse:
    """Day 2 先门控再选择证据，最后核验摘录；没有证据不返回引用。"""
    if not store.semantic:
        return _answer_baseline(store, request)
    from app.services.evidence import (
        EvidenceError,
        select_locally,
        select_with_deepseek,
    )
    if mode not in {"local", "deepseek"}:
        raise ValueError("回答模式仅支持 local 或 deepseek")
    if not 0 <= max_distance <= 2:
        raise ValueError("余弦距离阈值必须在 0–2 范围")
    request_id = str(uuid4())
    trace = trace if trace is not None else {}
    trace.update(request_id=request_id, mode=mode, reason=None, hits=[], accepted_ids=[],
                 citation_checks=[], max_distance=max_distance)
    refusal = AskResponse(answer="现有资料不足，无法回答；请补充文档或转人工确认。",
                          citations=[], grounded=False, request_id=request_id)
    chunks = retrieve(store, request.question, request.top_k, request.equipment_id)
    trace["hits"] = [{"text": chunk.text, "metadata": chunk.metadata, "distance": chunk.distance}
                     for chunk in chunks]
    if not chunks:
        trace["reason"] = "NO_RETRIEVAL_HITS"
        return refusal
    chunks = [chunk for chunk in chunks if chunk.distance <= max_distance]
    trace["accepted_ids"] = [chunk.metadata["chunk_id"] for chunk in chunks]
    if not chunks:
        trace["reason"] = "BELOW_THRESHOLD"
        return refusal
    try:
        selection = (select_with_deepseek(request.question, chunks, trace=trace) if mode == "deepseek"
                     else select_locally(request.question, chunks))
    except EvidenceError as exc:
        trace["reason"] = exc.reason
        return refusal
    except RuntimeError:
        trace["reason"] = "MODEL_ERROR"
        raise
    trace["selection"] = selection.model_dump()
    if not selection.supported:
        trace["reason"] = "MODEL_UNSUPPORTED" if mode == "deepseek" else "LOCAL_UNSUPPORTED"
        return refusal
    if not selection.quotes:
        trace["reason"] = "EMPTY_SELECTION"
        return refusal
    by_id = {str(chunk.metadata["chunk_id"]): chunk for chunk in chunks}
    citations = []
    for quote in selection.quotes:
        chunk = by_id.get(quote.chunk_id)
        # 全部通过才接受，不能只保留部分正确片段掩盖其他伪造引用。
        valid = chunk is not None and bool(quote.excerpt.strip()) and quote.excerpt in chunk.text
        trace["citation_checks"].append({"chunk_id": quote.chunk_id, "valid": valid})
        if not valid:
            trace["reason"] = "UNKNOWN_EVIDENCE_ID" if chunk is None else "EXCERPT_MISMATCH"
            return refusal
        citations.append(Citation(source_file=str(chunk.metadata["source_file"]),
                                  page=chunk.metadata.get("page"),
                                  source_url=chunk.metadata.get("source_url") or None,
                                  chunk_id=quote.chunk_id, excerpt=quote.excerpt,
                                  distance=round(chunk.distance, 6)))
    # 比较题至少要覆盖每个被点名的设备，不能丢弃一台设备的坏引用后当作完整回答。
    models = {model.upper().replace(" ", "") for model in
              re.findall(r"UR\d+e|IRB\s*\d+", request.question, re.IGNORECASE)}
    sources = [c.source_file.upper().replace("_", "").replace(" ", "") for c in citations]
    if any(not any(model in source for source in sources) for model in models):
        trace["reason"] = "INCOMPLETE_EVIDENCE"
        return refusal
    trace["reason"] = "ACCEPTED"
    answer = "以下为资料原文依据（以原文为准）：\n" + "\n".join(
        f"[{index}] {citation.source_file}：{citation.excerpt}"
        for index, citation in enumerate(citations, 1))
    return AskResponse(answer=answer, citations=citations, grounded=True, request_id=request_id)
