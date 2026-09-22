"""受保护问答：权限预筛选、检索后权威复核、距离门控、证据选择和最终授权。

只有授权且允许外发的候选才进入云端；验证编号、原文和版本，失败则拒答。
"""
import re
from uuid import uuid4

from app.core.config import MAX_DISTANCE
from app.retrieval.retriever import retrieve
from app.schemas.qa import AskRequest, AskResponse, Citation
from app.security.authorization import (
    can_process_externally,
    can_read,
    filter_authorized_chunks,
)
from app.services.evidence import EvidenceError, select_locally, select_with_deepseek


class ScopedStore:
    """Same interface for every retrieval branch, including model-comparison queries."""

    def __init__(self, store, policies, subject):
        self.store, self.policies, self.subject = store, policies, subject
        self.semantic = store.semantic

    def query(self, question, top_k, equipment_id=None):
        allowed = [p.resource_id for p in self.policies.list_policies()
                   if can_read(self.subject, p)]
        if not allowed:
            return {"documents": [[]], "metadatas": [[]], "distances": [[]]}
        return self.store.query(question, top_k, equipment_id, document_ids=allowed)


def authorized_answer(store, policies, sessions, token: str, request: AskRequest,
                      *, mode: str = "local", selector=None,
                      max_distance: float = MAX_DISTANCE) -> AskResponse:
    if mode not in {"local", "deepseek"} or not 0 <= max_distance <= 2:
        raise ValueError("Invalid answer configuration")
    initial = sessions.authenticate(token)
    refusal = AskResponse(answer="当前可用资料不足，请补充资料或联系管理员。",
                          citations=[], grounded=False, request_id=str(uuid4()))
    scoped = ScopedStore(store, policies, initial)
    accepted = []
    # Bounded over-fetch, never relax policy to fill top-k.
    for count in (request.top_k * 3, request.top_k * 6, request.top_k * 10):
        chunks = retrieve(scoped, request.question, count, request.equipment_id)
        labels = policies.get_many(list({c.metadata.get("document_id", "") for c in chunks}))
        accepted = filter_authorized_chunks(initial, chunks, labels)
        accepted = [c for c in accepted if c.distance <= max_distance]
        unique = {c.metadata["chunk_id"]: c for c in accepted}
        accepted = sorted(unique.values(), key=lambda c: c.distance)[:request.top_k]
        if len(accepted) >= request.top_k:
            break
    if not accepted:
        return refusal

    def revalidate():
        current = sessions.authenticate(token)
        if current != initial:
            return False
        latest = policies.get_many(list({c.metadata["document_id"] for c in accepted}))
        if len(filter_authorized_chunks(current, accepted, latest)) != len(accepted):
            return False
        if mode == "deepseek":
            return all(can_process_externally(current, latest.get(c.metadata["document_id"]))
                       for c in accepted)
        return True

    if not revalidate():
        return refusal
    # Only authorized candidates reach selectors; no pre-filter plaintext trace.
    try:
        choose = selector or (select_with_deepseek if mode == "deepseek" else select_locally)
        selection = choose(request.question, accepted)
    except EvidenceError:
        return refusal
    if not selection.supported or not selection.quotes:
        return refusal
    by_id = {c.metadata["chunk_id"]: c for c in accepted}
    citations = []
    for quote in selection.quotes:
        chunk = by_id.get(quote.chunk_id)
        if chunk is None or not quote.excerpt.strip() or quote.excerpt not in chunk.text:
            return refusal
        citations.append(Citation(document_id=chunk.metadata["document_id"],
                                  policy_version=chunk.metadata["policy_version"],
                                  content_version=chunk.metadata["content_version"],
                                  source_file=chunk.metadata["source_file"],
                                  page=chunk.metadata.get("page"),
                                  chunk_id=quote.chunk_id, excerpt=quote.excerpt,
                                  distance=chunk.distance))
    # Preserve the existing comparison completeness contract after authorization.
    models = {m.upper().replace(" ", "") for m in
              re.findall(r"UR\d+e|IRB\s*\d+", request.question, re.IGNORECASE)}
    sources = [c.source_file.upper().replace("_", "").replace(" ", "") for c in citations]
    if any(not any(model in source for source in sources) for model in models):
        return refusal
    # No output text or citation escapes before this final policy/session check.
    if not revalidate():
        return refusal
    return AskResponse(answer="资料原文依据：\n" + "\n".join(
        f"[{index}] {c.excerpt}" for index, c in enumerate(citations, 1)),
        citations=citations, grounded=True, request_id=refusal.request_id)
