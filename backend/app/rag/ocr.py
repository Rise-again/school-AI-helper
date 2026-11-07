"""云端 OCR 客户端（model-service 的 /v1/ocr）。

契约：
    POST {base}/v1/ocr   multipart(form-data)
        file:  原始文件（PDF/PNG/JPG，PDF 由服务端逐页栅格化）
        pages: 可选，"1,3,5" 只识别指定页；不传表示全部
    200 {"pages": [{"page_no": 1, "text": "..."}], "text": "可选的整体文本"}
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol

import httpx

from app.core.errors import DependencyUnavailable

# 页码 -> 文本；整文件识别时用 0 作为页码
PageTexts = dict[int, str]


class OcrClient(Protocol):
    async def ocr_file(self, path: Path, *, pages: list[int] | None = None) -> PageTexts: ...


class NullOcrClient:
    """未配置 OCR 时使用：不做任何事，让解析流程如实报告"无文本"。"""

    async def ocr_file(self, path: Path, *, pages: list[int] | None = None) -> PageTexts:
        return {}


class HttpOcrClient:
    def __init__(self, base_url: str, *, timeout: float = 120.0) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    async def ocr_file(self, path: Path, *, pages: list[int] | None = None) -> PageTexts:
        raw = await asyncio.to_thread(path.read_bytes)
        data = {"pages": ",".join(str(p) for p in pages)} if pages else {}
        files = {"file": (path.name, raw)}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(f"{self._base}/v1/ocr", files=files, data=data)
                resp.raise_for_status()
                payload = resp.json()
        except httpx.HTTPError as exc:
            raise DependencyUnavailable(f"OCR 服务不可用：{exc.__class__.__name__}") from exc
        except ValueError as exc:  # 非 JSON 响应
            raise DependencyUnavailable("OCR 服务返回格式不正确") from exc

        result: PageTexts = {}
        for item in payload.get("pages", []) or []:
            try:
                result[int(item["page_no"])] = str(item.get("text", ""))
            except (KeyError, TypeError, ValueError):
                continue
        if not result and payload.get("text"):
            result[0] = str(payload["text"])
        return result
