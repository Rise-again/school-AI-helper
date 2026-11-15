"""P8-01：文档解析分支测试（不读真实 PDF/docx）。"""

from __future__ import annotations

import asyncio

import pytest

from app.core.errors import ValidationFailed
from app.rag import parser as parser_mod
from app.rag.parser import DocumentParser, PageText


class FakeOcr:
    def __init__(self, pages=None, text=None):
        self.pages = pages
        self.text = text

    async def ocr_file(self, path, *, pages=None):
        if self.pages is not None:
            return self.pages
        if self.text is not None:
            return {0: self.text}
        return {}


def run(parser, path):
    return asyncio.run(parser.parse(path))


def test_parser_rejects_unsupported(tmp_path):
    path = tmp_path / "a.exe"
    path.write_bytes(b"x")
    with pytest.raises(ValidationFailed):
        run(DocumentParser(), path)


def test_parser_image_uses_ocr(tmp_path):
    path = tmp_path / "a.png"
    path.write_bytes(b"x")
    doc = run(DocumentParser(FakeOcr(text="图像里的文字" * 10)), path)
    assert doc.channel == "ocr"
    assert "图像里的文字" in doc.text


def test_parser_image_ocr_empty_warns(tmp_path):
    path = tmp_path / "a.jpg"
    path.write_bytes(b"x")
    doc = run(DocumentParser(FakeOcr()), path)
    assert doc.pages == []
    assert doc.warnings


def test_parser_pdf_page_mode_merges_ocr(tmp_path, monkeypatch):
    path = tmp_path / "a.pdf"
    path.write_bytes(b"%PDF")
    monkeypatch.setattr(parser_mod, "_pdf_pages", lambda p: ["短", "长" * 100])
    doc = run(DocumentParser(FakeOcr(pages={1: "OCR补齐" * 20})), path)
    assert doc.channel == "pdf-text+ocr"
    assert "OCR补齐" in doc.text
    assert any("OCR 补齐" in w for w in doc.warnings)


def test_parser_pdf_page_mode_ocr_missing_warns(tmp_path, monkeypatch):
    path = tmp_path / "a.pdf"
    path.write_bytes(b"%PDF")
    monkeypatch.setattr(parser_mod, "_pdf_pages", lambda p: ["短", "长" * 100])
    doc = run(DocumentParser(FakeOcr()), path)
    assert doc.channel == "pdf-text"
    assert any("OCR 未返回" in w for w in doc.warnings)


def test_parser_pdf_encrypted_raises(tmp_path, monkeypatch):
    path = tmp_path / "a.pdf"
    path.write_bytes(b"%PDF")

    def boom(_):
        raise ValidationFailed("PDF 已加密")

    monkeypatch.setattr(parser_mod, "_pdf_pages", boom)
    with pytest.raises(ValidationFailed):
        run(DocumentParser(), path)


def test_parser_markitdown_mode_and_empty_txt(tmp_path, monkeypatch):
    path = tmp_path / "a.docx"
    path.write_bytes(b"x")
    monkeypatch.setattr(parser_mod, "_to_markdown", lambda p: "正文" * 100)
    doc = run(DocumentParser(pdf_mode="markitdown"), path)
    assert doc.channel == "markitdown"
    assert doc.visible_chars > 0

    empty = tmp_path / "b.txt"
    empty.write_bytes(b"")
    monkeypatch.setattr(parser_mod, "_to_markdown", lambda p: "")
    doc = run(DocumentParser(), empty)
    assert doc.pages == []
    assert any("没有可见文本" in w for w in doc.warnings)


def test_merge_ocr_without_pages():
    merged = DocumentParser._merge_ocr([], {2: "第二页", 1: "第一页"})
    assert [p.page_no for p in merged] == [1, 2]
    assert PageText(1, "第一页").text == "第一页"
