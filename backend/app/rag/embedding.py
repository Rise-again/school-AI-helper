"""embedding 客户端（model-service 的 /v1/embeddings）。

契约（OpenAI 兼容）：
    POST {base}/v1/embeddings  {"input": ["文本1", ...], "model": "bge-large-zh-v1.5"}
    200 {"data": [{"index": 0, "embedding": [0.1, ...]}, ...], "model": "...", "usage": {...}}
维度必须是 1024；同一批里长度不一致直接报错，避免脏数据进库。
"""

from __future__ import annotations

import hashlib
import math
from typing import Protocol

import httpx

from app.core.errors import DependencyUnavailable

EXPECTED_DIM = 1024


class EmbeddingClient(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class HttpEmbeddingClient:
    def __init__(
        self,
        base_url: str,
        *,
        model: str = "bge-large-zh-v1.5",
        batch_size: int = 32,
        timeout: float = 180.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._model = model
        self._batch_size = batch_size
        self._timeout = timeout

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for start in range(0, len(texts), self._batch_size):
                batch = texts[start : start + self._batch_size]
                try:
                    resp = await client.post(
                        f"{self._base}/v1/embeddings",
                        json={"input": batch, "model": self._model},
                    )
                    resp.raise_for_status()
                    payload = resp.json()
                except httpx.HTTPError as exc:
                    raise DependencyUnavailable(
                        f"向量化服务不可用：{exc.__class__.__name__}"
                    ) from exc
                except ValueError as exc:
                    raise DependencyUnavailable("向量化服务返回格式不正确") from exc

                data = sorted(payload.get("data", []), key=lambda item: item.get("index", 0))
                if len(data) != len(batch):
                    raise DependencyUnavailable(
                        f"向量化返回数量不匹配：请求 {len(batch)} 条，返回 {len(data)} 条"
                    )
                for item in data:
                    vector = item.get("embedding") or []
                    if len(vector) != EXPECTED_DIM:
                        raise DependencyUnavailable(
                            f"向量维度异常：期望 {EXPECTED_DIM}，实际 {len(vector)}"
                        )
                    vectors.append([float(x) for x in vector])
        return vectors


class HashEmbeddingClient:
    """测试用：由文本哈希生成确定性单位向量，不依赖任何模型。"""

    def __init__(self, dim: int = 64) -> None:
        self._dim = dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        seed = text.encode("utf-8")
        raw: list[float] = []
        while len(raw) < self._dim:
            seed = hashlib.sha256(seed).digest()
            raw.extend((b - 127.5) / 127.5 for b in seed)
        vec = raw[: self._dim]
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]
