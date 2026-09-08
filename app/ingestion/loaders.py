from pathlib import Path


def load_txt(path: Path) -> str:
    """读取 UTF-8 文本；在入口处拒绝错误类型和空文档。"""
    if path.suffix.lower() != ".txt":
        raise ValueError("Day 1 baseline only accepts TXT files")
    text = path.read_text(encoding="utf-8-sig")
    if not text.strip():
        raise ValueError("Document is empty")
    return text
