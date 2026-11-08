"""重排客户端（model-service 的 /v1/rerank）。

交叉编码器比向量召回慢一个数量级，所以只对召回的 topK 做重排（默认 20 条）。
服务不可用时降级为 NoopReranker：保持召回顺序，不阻断问答。
"""

from __future__ import annotations

import logging
from typing import Protocol

import httpx

from app.core.errors import DependencyUnavailable

logger = logging.getLogger("campus.rerank")


class RerankerClient(Protocol):
    async def rerank(self, query: str, passages: list[str]) -> list[float]: ...


class HttpRerankerClient:
    def __init__(self, base_url: str, *, model: str = "bge-reranker-v2-m3", timeout: float = 30.0) -> None:
        self._base = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout

    async def rerank(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base}/v1/rerank",
                    json={"query": query, "passages": passages, "model": self._model},
                )
                resp.raise_for_status()
                payload = resp.json()
        except httpx.HTTPError as exc:
            raise DependencyUnavailable(f"重排服务不可用：{exc.__class__.__name__}") from exc
        except ValueError as exc:
            raise DependencyUnavailable("重排服务返回格式不正确") from exc

        scores = [0.0] * len(passages)
        for item in payload.get("results", []):
            idx = int(item["index"])
            if 0 <= idx < len(scores):
                scores[idx] = float(item["relevance_score"])
        return scores


class NoopReranker:
    """降级实现：不做重排，分数恒为 0，由调用方按阈值决定是否放过。"""

    def __init__(self, *, score: float = 1.0) -> None:
        self._score = score

    async def rerank(self, query: str, passages: list[str]) -> list[float]:
        return [self._score] * len(passages)
