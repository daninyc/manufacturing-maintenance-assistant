import json
import re
from dataclasses import dataclass
from typing import Any

from app.core.config import PROJECT_ROOT
from app.retrieval.vector_store import LocalChromaStore


@dataclass(frozen=True)
class RetrievedChunk:
    text: str
    metadata: dict[str, Any]
    distance: float


def retrieve(store: LocalChromaStore, question: str, top_k: int,
             equipment_id: str | None = None) -> list[RetrievedChunk]:
    """把 Chroma 的列式结果整理成对象，同时保留来源和距离。

    当前集合使用余弦距离：值越小表示向量越接近。阈值必须通过 Day 6
    评测确定，不能凭感觉写成“最佳值”。
    """
    if store.semantic:
        models = list(dict.fromkeys(
            model.upper().replace(" ", "") for model in re.findall(r"UR\d+e|IRB\s*\d+", question, re.IGNORECASE)))
        if models:
            manifest = json.loads((PROJECT_ROOT / "data/raw_docs/manifest.json").read_text(encoding="utf-8"))
            fields = [name for pattern, name in [(r"负载|载荷|承重|payload", "最大负载"),
                      (r"半径|臂展|范围|reach", "工作半径"), (r"温度|temperature", "环境温度")]
                      if re.search(pattern, question, re.IGNORECASE)]
            gathered = []
            for model in models:
                ids = {item["equipment_id"] for item in manifest
                       if item["document_id"].split("-")[0].upper() == model}
                if len(ids) != 1:
                    return []
                asset = next(iter(ids))
                if equipment_id and equipment_id != asset:
                    return []
                # 比较题为每台设备保留候选配额，避免全被一台设备占据。
                count = max(1, top_k // len(models))
                query = f"{model} {' '.join(fields)}" if fields else question
                gathered.extend(_unpack(store.query(query, count, asset)))
            return sorted(gathered, key=lambda chunk: chunk.distance)[:top_k]
    result = store.query(question, top_k, equipment_id)
    return _unpack(result)


def _unpack(result: dict) -> list[RetrievedChunk]:
    """把列式数组一一对齐，长度不一致立即报错。"""
    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]
    return [
        RetrievedChunk(text=document, metadata=metadata, distance=float(distance))
        for document, metadata, distance in zip(documents, metadatas, distances, strict=True)
    ]
