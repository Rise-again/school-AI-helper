"""云端模型服务的三个模型后端。

设计原则
- **惰性加载**：进程起来不加载模型，第一次请求时才加载（vLLM 冷启动已经很慢，不想再叠一层）。
- **可替换**：`ModelBackend` 协议让单元测试能注入假后端，不需要 GPU 和真实权重。
- **失败要响**：加载失败保留错误原因，`/healthz` 如实报告，不假装健康。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

logger = logging.getLogger("models")


class ModelBackend(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...
    def rerank(self, query: str, passages: list[str]) -> list[float]: ...
    def ocr(self, path: Path, pages: list[int] | None) -> dict[int, str]: ...
    def status(self) -> dict[str, str]: ...


@dataclass
class LocalBackend:
    """真实实现：FlagEmbedding 做向量与重排，PaddleOCR 做 OCR。"""

    embed_path: str
    rerank_path: str
    dim: int = 1024
    device: str = "cuda"
    use_fp16: bool = True
    ocr_lang: str = "ch"
    _embed_model: object | None = field(default=None, init=False)
    _rerank_model: object | None = field(default=None, init=False)
    _ocr_model: object | None = field(default=None, init=False)
    _errors: dict[str, str] = field(default_factory=dict, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    # ---------- 惰性加载 ----------
    def _get_embed(self):
        with self._lock:
            if self._embed_model is None:
                from FlagEmbedding import FlagModel

                logger.info("loading_embedding", extra={"path": self.embed_path})
                self._embed_model = FlagModel(
                    self.embed_path,
                    query_instruction_for_retrieval=None,
                    use_fp16=self.use_fp16,
                    devices=self.device,
                )
            return self._embed_model

    def _get_rerank(self):
        with self._lock:
            if self._rerank_model is None:
                from FlagEmbedding import FlagReranker

                logger.info("loading_reranker", extra={"path": self.rerank_path})
                self._rerank_model = FlagReranker(
                    self.rerank_path, use_fp16=self.use_fp16, devices=self.device
                )
            return self._rerank_model

    def _get_ocr(self):
        with self._lock:
            if self._ocr_model is None:
                from paddleocr import PaddleOCR

                logger.info("loading_ocr", extra={"lang": self.ocr_lang})
                self._ocr_model = PaddleOCR(use_doc_orientation_classify=False, lang=self.ocr_lang)
            return self._ocr_model

    # ---------- 推理 ----------
    def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._get_embed()
        vectors = model.encode(texts, normalize_embeddings=True, batch_size=16)
        return [[float(x) for x in vec] for vec in vectors]

    def rerank(self, query: str, passages: list[str]) -> list[float]:
        model = self._get_rerank()
        pairs = [[query, p] for p in passages]
        scores = model.compute_score(pairs, normalize=True)
        if isinstance(scores, float):
            return [float(scores)]
        return [float(s) for s in scores]

    def ocr(self, path: Path, pages: list[int] | None) -> dict[int, str]:
        model = self._get_ocr()
        images = _rasterize(path, pages)
        result: dict[int, str] = {}
        for page_no, image in images:
            raw = model.predict(image)
            result[page_no] = _join_ocr_lines(raw)
        return result

    def status(self) -> dict[str, str]:
        return {
            "embedding": "loaded" if self._embed_model else self._errors.get("embedding", "not_loaded"),
            "rerank": "loaded" if self._rerank_model else self._errors.get("rerank", "not_loaded"),
            "ocr": "loaded" if self._ocr_model else self._errors.get("ocr", "not_loaded"),
        }


def _rasterize(path: Path, pages: list[int] | None) -> list[tuple[int, object]]:
    """把 PDF 转成逐页图像；图片文件直接返回。页码从 1 开始。"""
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
        from PIL import Image

        return [(0, Image.open(path).convert("RGB"))]

    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    targets = pages if pages else list(range(1, len(pdf) + 1))
    images: list[tuple[int, object]] = []
    for page_no in targets:
        if page_no < 1 or page_no > len(pdf):
            continue
        page = pdf[page_no - 1]
        images.append((page_no, page.render(scale=2.0).to_pil().convert("RGB")))
    return images


def _join_ocr_lines(raw: object) -> str:
    """兼容 PaddleOCR 2.x（[[box,(text,score)],...]）与 3.x（dict/对象）两种返回。"""
    lines: list[str] = []

    def walk(node: object) -> None:
        if node is None:
            return
        if isinstance(node, str):
            lines.append(node)
            return
        if isinstance(node, dict):
            texts = node.get("rec_texts") or node.get("texts")
            if texts:
                lines.extend(str(t) for t in texts)
                return
            for value in node.values():
                walk(value)
            return
        if isinstance(node, (list, tuple)):
            # 2.x 的 [box, (text, score)]
            if len(node) == 2 and isinstance(node[1], (list, tuple)) and node[1] and isinstance(node[1][0], str):
                lines.append(node[1][0])
                return
            for item in node:
                walk(item)
            return
        texts = getattr(node, "rec_texts", None)
        if texts:
            lines.extend(str(t) for t in texts)

    walk(raw)
    return "\n".join(line for line in lines if line.strip())
