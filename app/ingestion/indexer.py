from pathlib import Path

from app.ingestion.cleaner import clean_text
from app.ingestion.loaders import load_txt
from app.ingestion.splitter import split_text
from app.retrieval.vector_store import LocalChromaStore


def index_txt(path: Path, store: LocalChromaStore) -> int:
    """完成读取、清洗、分块和入库，并把可追溯信息与文本一起保存。"""
    chunks = split_text(clean_text(load_txt(path)), path.stem)
    store.upsert(
        ids=[chunk.chunk_id for chunk in chunks],
        documents=[chunk.text for chunk in chunks],
        metadatas=[
            {
                # 引用来自这里保存的 metadata，不允许模型自行编造来源。
                "source_file": path.name,
                "document_id": path.stem,
                "chunk_id": chunk.chunk_id,
                "start": chunk.start,
                "end": chunk.end,
            }
            for chunk in chunks
        ],
    )
    return len(chunks)
