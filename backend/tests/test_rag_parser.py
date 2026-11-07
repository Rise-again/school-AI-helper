"""解析器的行为测试：重点验证"空文本必须转 OCR"这条防线。"""

from __future__ import annotations

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


def test_empty_file_falls_back_to_ocr(tmp_path):
    path = tmp_path / "scan.txt"
    path.write_text("", encoding="utf-8")
    ocr = FakeOcr("OCR 识别出的正文内容，关于奖助学金评定办法。")
    import asyncio

    parsed = asyncio.run(DocumentParser(ocr).parse(path))
    assert parsed.channel == "ocr"
    assert "奖助学金" in parsed.text
    assert ocr.calls, "空文本必须调用 OCR"


def test_empty_file_without_ocr_reports_warning(tmp_path):
    path = tmp_path / "scan.txt"
    path.write_text("", encoding="utf-8")
    import asyncio

    parsed = asyncio.run(DocumentParser().parse(path))
    assert parsed.pages == []
    assert any("OCR" in w for w in parsed.warnings)


def test_unsupported_suffix_rejected(tmp_path):
    path = tmp_path / "archive.zip"
    path.write_bytes(b"PK\x03\x04")
    import asyncio

    with pytest.raises(ValidationFailed):
        asyncio.run(DocumentParser().parse(path))


def test_short_text_triggers_ocr(tmp_path):
    path = tmp_path / "stub.txt"
    path.write_text("目录", encoding="utf-8")  # 可见字符 < 50
    ocr = FakeOcr("完整正文：本规定适用于全校本科生。")
    import asyncio

    parsed = asyncio.run(DocumentParser(ocr, min_chars=50).parse(path))
    assert parsed.channel == "ocr"
