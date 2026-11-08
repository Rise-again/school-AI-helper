"""解析器的行为测试：重点验证"空文本必须转 OCR"这条防线。"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from app.core.errors import ValidationFailed
from app.rag.parser import DocumentParser


class FakeOcr:
    def __init__(self, text: str = "") -> None:
        self.text = text
        self.calls: list[list[int] | None] = []

    async def ocr_file(self, path, *, pages=None):
        self.calls.append(pages)
        if not self.text:
            return {}
        if pages:
            return {p: self.text for p in pages}
        return {0: self.text}


def test_text_file_is_parsed(tmp_path):
    path = tmp_path / "notice.txt"
    path.write_text("关于 2026 年寒假放假安排的通知\n\n学生自 1 月 10 日起放假，2 月 20 日报到。", encoding="utf-8")
    import asyncio

    parsed = asyncio.run(DocumentParser().parse(path))
    assert parsed.channel == "markitdown"
    assert "寒假" in parsed.text
    assert parsed.visible_chars > 20


PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _tiny_png(tmp_path) -> "Path":
    path = tmp_path / "scan.png"
    path.write_bytes(PNG_1PX)
    return path


def test_image_without_text_falls_back_to_ocr(tmp_path):
    """只有 PDF/图片才走 OCR：1px 图片没有文本层，应当调用 OCR。"""
    ocr = FakeOcr("OCR 识别出的正文内容，关于奖助学金评定办法。")
    import asyncio

    parsed = asyncio.run(DocumentParser(ocr).parse(_tiny_png(tmp_path)))
    assert parsed.channel == "ocr"
    assert "奖助学金" in parsed.text
    assert ocr.calls, "图像类文件必须有文本层缺失时调用 OCR"


def test_image_without_ocr_reports_warning(tmp_path):
    import asyncio

    parsed = asyncio.run(DocumentParser().parse(_tiny_png(tmp_path)))
    assert parsed.pages == []
    assert any("OCR" in w for w in parsed.warnings)


def test_unsupported_suffix_rejected(tmp_path):
    path = tmp_path / "archive.zip"
    path.write_bytes(b"PK\x03\x04")
    import asyncio

    with pytest.raises(ValidationFailed):
        asyncio.run(DocumentParser().parse(path))


def test_short_text_document_is_not_sent_to_ocr(tmp_path):
    """短 txt 是真内容，不能被当成扫描件送去 OCR（OCR 只认 PDF/图片）。"""
    path = tmp_path / "short.txt"
    path.write_text("补考定于 3 月 15 日。", encoding="utf-8")
    ocr = FakeOcr("不该被调用")
    import asyncio

    parsed = asyncio.run(DocumentParser(ocr, min_chars=50).parse(path))
    assert parsed.channel == "markitdown"
    assert "补考" in parsed.text
    assert ocr.calls == []
