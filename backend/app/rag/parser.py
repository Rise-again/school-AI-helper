"""文档解析。

- 办公格式（docx/pptx/xlsx/html/txt…）：MarkItDown 转 Markdown。
- PDF：默认按页抽取文本（保留页码，引用才能指到"第几页"）；
        可用 PARSE_PDF_MODE=markitdown 切回整篇转换。
- 空文本分流（计划 3.2 第 3 条）：任何页面可见字符 < OCR_MIN_CHARS 即判为文本层缺失，
  交给云端 PaddleOCR；整篇都空则整篇走 OCR。MarkItDown 对扫描件会**静默返回空串**，
  这一步是防止"解析成功但内容为空"的唯一防线。
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.core.errors import ValidationFailed
from app.rag.ocr import NullOcrClient, OcrClient

logger = logging.getLogger("campus.parser")

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}

SUPPORTED_SUFFIXES = {
    ".pdf",
    ".docx",
    ".doc",
    ".pptx",
    ".xlsx",
    ".xls",
    ".html",
    ".htm",
    ".txt",
    ".md",
    ".csv",
} | IMAGE_SUFFIXES

_WS = re.compile(r"\s+")

# 只有这些格式才值得送 OCR：纯文本类再短也不该走图像识别
OCR_SUFFIXES = {".pdf"} | IMAGE_SUFFIXES


@dataclass
class PageText:
    page_no: int | None
    text: str


@dataclass
class ParsedDocument:
    pages: list[PageText]
    channel: str  # markitdown / pdf-text / ocr / pdf-text+ocr
    warnings: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n\n".join(p.text for p in self.pages if p.text.strip())

    @property
    def visible_chars(self) -> int:
        return len(_WS.sub("", self.text))

    def as_pages(self) -> list[tuple[int | None, str]]:
        return [(p.page_no, p.text) for p in self.pages if p.text.strip()]


def _clean(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+$", "", text, flags=re.M)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _to_markdown(path: Path) -> str:
    from markitdown import MarkItDown  # 延迟导入：不装解析依赖也能起服务

    converter = MarkItDown()
    result = converter.convert(str(path))
    return result.text_content or ""


def _pdf_pages(path: Path) -> list[str]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    if reader.is_encrypted:
        raise ValidationFailed("PDF 已加密，无法解析")
    pages: list[str] = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception as exc:  # noqa: BLE001 - 单页损坏不影响整篇
            logger.warning("pdf_page_extract_failed", extra={"error": str(exc)})
            pages.append("")
    return pages


class DocumentParser:
    def __init__(
        self,
        ocr: OcrClient | None = None,
        *,
        pdf_mode: str = "page",
        min_chars: int = 50,
    ) -> None:
        self._ocr = ocr or NullOcrClient()
        self._pdf_mode = pdf_mode
        self._min_chars = min_chars

    async def parse(self, path: Path) -> ParsedDocument:
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise ValidationFailed(f"不支持的文件类型：{suffix or '未知'}")

        warnings: list[str] = []
        if suffix in IMAGE_SUFFIXES:
            # 图片没有文本层，直接交给 OCR，不经过 MarkItDown
            pages = []
            channel = "ocr"
        elif suffix == ".pdf" and self._pdf_mode == "page":
            pages, warnings = await self._parse_pdf(path)
            channel = "pdf-text"
        else:
            md = await asyncio.to_thread(_to_markdown, path)
            pages = [PageText(page_no=None, text=_clean(md))]
            channel = "markitdown"

        # 整篇几乎没文字 → 仅对可 OCR 的格式走图像识别。
        # 纯文本类（txt/md/docx…）再短也是真内容，不能送去 OCR，否则会被 OCR 服务拒收。
        if self._visible(pages) < self._min_chars and suffix in OCR_SUFFIXES:
            ocr_text = await self._ocr.ocr_file(path)
            if ocr_text:
                pages = self._merge_ocr(pages, ocr_text)
                channel = "ocr"
            else:
                warnings.append("未提取到文本，且 OCR 未返回内容（可能是纯图片或加密文档）")
        elif self._visible(pages) == 0:
            warnings.append("文档没有可见文本")

        doc = ParsedDocument(
            pages=[p for p in pages if p.text.strip()],
            channel=channel,
            warnings=warnings,
            meta={"suffix": suffix, "size_bytes": path.stat().st_size},
        )
        return doc

    # ---------- 内部 ----------
    @staticmethod
    def _visible(pages: list[PageText]) -> int:
        return len(_WS.sub("", "".join(p.text for p in pages)))

    async def _parse_pdf(self, path: Path) -> tuple[list[PageText], list[str]]:
        raw_pages = await asyncio.to_thread(_pdf_pages, path)
        pages = [PageText(page_no=i + 1, text=_clean(t)) for i, t in enumerate(raw_pages)]
        warnings: list[str] = []

        thin = [p.page_no for p in pages if p.page_no and len(_WS.sub("", p.text)) < self._min_chars]
        if thin:
            ocr_text = await self._ocr.ocr_file(path, pages=thin)
            if ocr_text:
                pages = self._merge_ocr(pages, ocr_text)
                warnings.append(f"{len(thin)} 页文本层缺失，已用 OCR 补齐")
            else:
                warnings.append(f"{len(thin)} 页文本层缺失，OCR 未返回内容")
        return pages, warnings

    @staticmethod
    def _merge_ocr(pages: list[PageText], ocr_text: dict[int, str]) -> list[PageText]:
        if not pages:
            return [PageText(page_no=pg, text=_clean(t)) for pg, t in sorted(ocr_text.items())]
        merged: list[PageText] = []
        for page in pages:
            replacement = ocr_text.get(page.page_no or 0) or ocr_text.get(page.page_no or -1)
            text = _clean(replacement) if replacement and len(replacement) > len(page.text) else page.text
            merged.append(PageText(page_no=page.page_no, text=text))
        # OCR 返回了页码但没有对应页面（例如整篇 OCR，page_no=0）
        if 0 in ocr_text and all(not p.text.strip() for p in merged):
            merged = [PageText(page_no=None, text=_clean(ocr_text[0]))]
        return merged
