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

    def __init__(self, path: Path, collection_name: str, *, semantic: bool = False) -> None:
        self.semantic = semantic
        path.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(path))
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine", "embedding": "bge-small-zh-v1.5" if semantic else "hash-v1"},
        )
        expected = "bge-small-zh-v1.5" if semantic else "hash-v1"
        if self.collection.metadata.get("embedding", "hash-v1") != expected:
            raise ValueError("集合 embedding 不一致，请使用新集合，不能混入不同向量模型")

    def reset(self) -> None:
        name = self.collection.name
        self.client.delete_collection(name)
        self.collection = self.client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine",
                      "embedding": "bge-small-zh-v1.5" if self.semantic else "hash-v1"},
        )

    def upsert(self, ids: list[str], documents: list[str], metadatas: list[dict[str, Any]]) -> None:
        # ponytail: hash embedding 只适合基线；Day 2 有真实语义召回需求时替换。
        if self.semantic:
            from app.retrieval.embedding import embed_texts
            # 来源网址和清单字段会稀释语义；仅从向量输入移除，原文与 metadata 原样保留。
            semantic_texts = []
            for document, metadata in zip(documents, metadatas, strict=True):
                body = re.sub(
                    r"(?m)^(document_id|version|published_at|equipment_id|equipment_type|source_type|source_url):.*\n?",
                    "", document)
                semantic_texts.append(f"{metadata.get('document_id', '')}\n{body}")
            embeddings = embed_texts(semantic_texts)
        else:
            embeddings = [hash_embedding(document) for document in documents]
        self.collection.upsert(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)

    def query(self, question: str, top_k: int, equipment_id: str | None = None,
              *, document_ids: list[str] | None = None) -> dict[str, Any]:
        if document_ids == [] or self.collection.count() == 0:
            return {"documents": [[]], "metadatas": [[]], "distances": [[]]}
        if self.semantic:
            from app.retrieval.embedding import embed_texts
            vectors = embed_texts([question], query=True)
        else:
            vectors = [hash_embedding(question)]
        conditions = []
        if equipment_id:
            conditions.append({"equipment_id": equipment_id})
        if document_ids is not None:
            conditions.append({"document_id": {"$in": document_ids}})
        where = ({"$and": conditions} if len(conditions) > 1
                 else conditions[0] if conditions else None)
        return self.collection.query(
            query_embeddings=vectors,
            n_results=min(top_k, self.collection.count()),
            where=where,
            include=["documents", "metadatas", "distances"],
        )
