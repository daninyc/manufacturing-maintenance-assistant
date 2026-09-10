from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from app.ingestion.cleaner import clean_text


@dataclass(frozen=True)
class Document:
    """统一输入单元：TXT 为一份，PDF 每页一份，页码从 1 开始。"""

    text: str
    metadata: dict[str, str | int]


def load_documents(path: Path, *, document_id: str | None = None,
                   equipment_type: str = "unknown", version: str = "unknown",
                   source_url: str = "", equipment_id: str = "",
                   source_type: str = "unknown", published_at: str = "unknown") -> list[Document]:
    """完整验证后返回，避免多页 PDF 部分失败却被当作完整文档。

    不猜测编码、不做 OCR；重复页眉页脚只按严格首尾行规则处理。
    """
    path = Path(path)
    if path.suffix.lower() not in {".txt", ".pdf"}:
        raise ValueError(f"仅支持 PDF/TXT：{path.name}")
    if not path.is_file():
        raise ValueError(f"文件不存在：{path}")
    if path.stat().st_size == 0:
        raise ValueError(f"空文件：{path.name}")
    if path.suffix.lower() == ".txt":
        try:
            pages = [path.read_text(encoding="utf-8-sig")]
        except UnicodeError as exc:
            raise ValueError(f"TXT 必须是 UTF-8 编码：{path.name}") from exc
    else:
        try:
            reader = PdfReader(path)
            if reader.is_encrypted:
                raise ValueError(f"加密 PDF，请提供未加密副本：{path.name}")
            pages = [page.extract_text() or "" for page in reader.pages]
        except (PyPdfError, OSError, ValueError) as exc:
            raise ValueError(f"PDF 读取失败：{path.name}；{exc}") from exc
        if not pages:
            raise ValueError(f"PDF 没有页面：{path.name}")

    for number, text in enumerate(pages, 1):
        if not text.strip():
            raise ValueError(f"空文本或扫描图片页：{path.name} 第 {number} 页；不支持 OCR")
        if "\ufffd" in text or "\x00" in text:
            raise ValueError(f"检测到乱码：{path.name} 第 {number} 页；请重新导出原文")

    lines = [[line.strip() for line in text.splitlines() if line.strip()] for text in pages]
    # ponytail: 仅删除所有页首尾完全相同且不含数字的行；复杂版式后续再加规则。
    if len(lines) >= 3:
        edges = Counter(line for page in lines for line in {page[0], page[-1]})
        repeated = {line for line, count in edges.items()
                    if count == len(lines) and not any(char.isdigit() for char in line)}
        lines = [[line for index, line in enumerate(page)
                  if not (index in {0, len(page) - 1} and line in repeated)] for page in lines]

    documents = []
    for number, page in enumerate(lines, 1):
        text = clean_text("\n".join(page))
        if not text:
            raise ValueError(f"清洗后为空：{path.name} 第 {number} 页")
        documents.append(Document(text, {
            "source_file": path.name, "page": number,
            "document_id": document_id or path.stem,
            "equipment_type": equipment_type, "version": version,
            "source_url": source_url, "equipment_id": equipment_id,
            "source_type": source_type, "published_at": published_at,
        }))
    return documents


def load_txt(path: Path) -> str:
    """保留 Day 1 接口，读取逻辑复用统一加载器。"""
    if path.suffix.lower() != ".txt":
        raise ValueError("load_txt 仅接受 TXT")
    return load_documents(path)[0].text
