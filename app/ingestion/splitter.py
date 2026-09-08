from dataclasses import dataclass


@dataclass(frozen=True)
class TextChunk:
    chunk_id: str
    text: str
    start: int
    end: int


def split_text(text: str, document_id: str, chunk_size: int = 500, overlap: int = 80) -> list[TextChunk]:
    """按字符切块；重叠区域减少答案恰好落在块边界时的信息丢失。"""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be non-negative and smaller than chunk_size")
    chunks: list[TextChunk] = []
    start = 0
    index = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        # 稳定 ID 让同一文档重复入库时走 upsert，而不是生成重复数据。
        chunks.append(TextChunk(f"{document_id}::chunk-{index:04d}", text[start:end], start, end))
        if end == len(text):
            break
        start = end - overlap
        index += 1
    return chunks
