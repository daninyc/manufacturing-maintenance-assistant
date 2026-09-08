import hashlib
import re
from pathlib import Path
from typing import Any

import chromadb


def hash_embedding(text: str, dimensions: int = 256) -> list[float]:
    """把词元稳定映射为归一化向量，仅用于验证 Day 1 数据链路。

    原理：相同词元落到相同维度，重合越多，余弦距离通常越小。
    它不理解语义，不能用来证明真实 RAG 效果。
    """
    vector = [0.0] * dimensions
    tokens = re.findall(r"[\u4e00-\u9fff]|[a-z0-9_]+", text.lower())
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        position = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[position] += sign
    norm = sum(value * value for value in vector) ** 0.5
    return [value / norm for value in vector] if norm else vector


class LocalChromaStore:
    """最薄的 Chroma 封装：持久化、幂等写入和余弦距离查询。"""

    def __init__(self, path: Path, collection_name: str) -> None:
        path.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(path))
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def reset(self) -> None:
        name = self.collection.name
        self.client.delete_collection(name)
        self.collection = self.client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert(self, ids: list[str], documents: list[str], metadatas: list[dict[str, Any]]) -> None:
        # ponytail: hash embedding 只适合基线；Day 2 有真实语义召回需求时替换。
        embeddings = [hash_embedding(document) for document in documents]
        self.collection.upsert(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)

    def query(self, question: str, top_k: int) -> dict[str, Any]:
        return self.collection.query(
            query_embeddings=[hash_embedding(question)],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
