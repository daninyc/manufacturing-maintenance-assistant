from dataclasses import dataclass
from typing import Any

from app.retrieval.vector_store import LocalChromaStore


@dataclass(frozen=True)
class RetrievedChunk:
    text: str
    metadata: dict[str, Any]
    distance: float


def retrieve(store: LocalChromaStore, question: str, top_k: int) -> list[RetrievedChunk]:
    """把 Chroma 的列式结果整理成对象，同时保留来源和距离。

    当前集合使用余弦距离：值越小表示向量越接近。阈值必须通过 Day 6
    评测确定，不能凭感觉写成“最佳值”。
    """
    result = store.query(question, top_k)
    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]
    return [
        RetrievedChunk(text=document, metadata=metadata, distance=float(distance))
        for document, metadata, distance in zip(documents, metadatas, distances, strict=True)
    ]
