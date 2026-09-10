"""Day 2 中文语义向量；缓存放在项目 D 盘目录。"""
from functools import lru_cache

from fastembed import TextEmbedding

from app.core.config import PROJECT_ROOT

MODEL_NAME = "BAAI/bge-small-zh-v1.5"


@lru_cache(maxsize=1)
def get_model() -> TextEmbedding:
    """同一进程只加载一次 ONNX 模型，避免每次提问重新加载权重。"""
    return TextEmbedding(model_name=MODEL_NAME, cache_dir=str(PROJECT_ROOT / "data/models"),
                         threads=2)


def embed_texts(texts: list[str], *, query: bool = False) -> list[list[float]]:
    """文档与问题使用同一模型；问题使用模型要求的 query 前缀。"""
    model = get_model()
    vectors = model.query_embed(texts) if query else model.passage_embed(texts)
    return [vector.tolist() for vector in vectors]
