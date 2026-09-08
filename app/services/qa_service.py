from uuid import uuid4

from app.retrieval.retriever import retrieve
from app.retrieval.vector_store import LocalChromaStore
from app.schemas.qa import AskRequest, AskResponse, Citation


def answer_question(store: LocalChromaStore, request: AskRequest) -> AskResponse:
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
            chunk_id=str(chunk.metadata["chunk_id"]),
            excerpt=chunk.text[:240],
            distance=round(chunk.distance, 6),
        )
        for chunk in chunks
    ]
    # ponytail: Day 1 只证明链路可运行；需要自然语言生成时再接入模型 API。
    answer = f"基线测试替身根据首条命中文本回答：{chunks[0].text}"
    return AskResponse(answer=answer, citations=citations, grounded=True, request_id=request_id)
