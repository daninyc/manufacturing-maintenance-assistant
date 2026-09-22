from pathlib import Path

from app.ingestion.loaders import load_documents
from app.ingestion.splitter import split_text
from app.retrieval.vector_store import LocalChromaStore


def index_txt(path: Path, store: LocalChromaStore) -> int:
    """完成读取、清洗、分块和入库，并把可追溯信息与文本一起保存。"""
    if path.suffix.lower() != ".txt":
        raise ValueError("index_txt 仅接受 TXT")
    return index_document(path, store)


def index_document(path: Path, store: LocalChromaStore, **metadata: str) -> int:
    """逐页分块，页码进入稳定 ID，避免不同页的块相互覆盖。"""
    documents = load_documents(path, **metadata)
    chunks = []
    metadatas = []
    for document in documents:
        page_id = f"{document.metadata['document_id']}::page-{document.metadata['page']}"
        for chunk in split_text(document.text, page_id):
            chunks.append(chunk)
            metadatas.append({**document.metadata, "chunk_id": chunk.chunk_id,
                              "start": chunk.start, "end": chunk.end})
    store.upsert(
        ids=[chunk.chunk_id for chunk in chunks],
        documents=[chunk.text for chunk in chunks],
        metadatas=metadatas,
    )
    # 新块成功写入后，才删除同一文档已经不存在的旧块；其他文档不受影响。
    document_id = documents[0].metadata["document_id"]
    current_ids = {chunk.chunk_id for chunk in chunks}
    old = store.collection.get(where={"document_id": document_id}, include=[])
    stale = [chunk_id for chunk_id in old["ids"] if chunk_id not in current_ids]
    if stale:
        store.collection.delete(ids=stale)
    return len(chunks)
