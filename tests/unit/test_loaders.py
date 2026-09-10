from pathlib import Path

import pytest
from pypdf import PdfWriter

from app.ingestion.loaders import load_documents, load_txt


def test_txt_metadata_and_preserved_codes(tmp_path: Path) -> None:
    path = tmp_path / "example.txt"
    path.write_text("\ufeffE-001  500 mm\n\n\n3 kg", encoding="utf-8")
    document = load_documents(path, document_id="DOC", equipment_type="robot", version="v1")[0]
    assert document.text == "E-001 500 mm\n3 kg"
    assert document.metadata["page"] == 1
    assert document.metadata["document_id"] == "DOC"
    assert document.metadata["version"] == "v1"
    assert load_txt(path) == document.text


@pytest.mark.parametrize("content", [b"", b"   \n", b"\xff", b"bad\x00text"])
def test_invalid_txt(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "invalid.txt"
    path.write_bytes(content)
    with pytest.raises(ValueError):
        load_documents(path)


@pytest.mark.parametrize("encrypted", [False, True])
def test_image_only_or_encrypted_pdf(tmp_path: Path, encrypted: bool) -> None:
    path = tmp_path / "invalid.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    if encrypted:
        writer.encrypt("test-password")
    writer.write(path)
    with pytest.raises(ValueError, match="加密|扫描"):
        load_documents(path)


def test_missing_unsupported_and_corrupt(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="不存在"):
        load_documents(tmp_path / "missing.txt")
    with pytest.raises(ValueError, match="仅支持"):
        load_documents(tmp_path / "wrong.csv")
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"not a PDF")
    with pytest.raises(ValueError, match="PDF 读取失败"):
        load_documents(path)
