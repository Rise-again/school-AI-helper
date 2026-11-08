"""检索：向量召回 → 元数据过滤（含时效）→ 重排 → 阈值截断。

顺序有讲究：
1. 召回 top_k（默认 20），宁多勿少；
2. **先过滤再重排**——重排是逐对打分，把过期或已删除的候选送进去纯属浪费算力；
3. 重排后按阈值截断，最后取 top_n。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace
from datetime import date
from typing import Any

from app.core.errors import DependencyUnavailable
from app.rag.embedding import EmbeddingClient
from app.rag.rerank import RerankerClient
from app.rag.store import VectorStore
from app.repositories.kb import KbRepository

logger = logging.getLogger("campus.retriever")


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    content: str
    score: float          # 重排后的相关性
    recall_score: float   # 向量召回分
    kb_file_id: int
    filename: str
    page_no: int | None
    heading_path: str
    source_url: str | None
    expired: bool


class Retriever:
    def __init__(
        self,
        *,
        embedder: EmbeddingClient,
        reranker: RerankerClient,
        store: VectorStore,
        kb_repo: KbRepository,
        top_k: int = 20,
        top_n: int = 5,
        threshold: float = 0.35,
    ) -> None:
        self._embedder = embedder
        self._reranker = reranker
        self._store = store
        self._kb_repo = kb_repo
        self._top_k = top_k
        self._top_n = top_n
        self._threshold = threshold

    async def search(
        self,
        query: str,
        *,
        top_n: int | None = None,
        include_expired: bool = False,
    ) -> list[RetrievedChunk]:
        query = query.strip()
        if not query:
            return []

        vectors = await self._embedder.embed([query])
        if not vectors:
            raise DependencyUnavailable("查询向量化失败")
        hits = await asyncio.to_thread(self._store.query, embedding=vectors[0], top_k=self._top_k)
        if not hits:
            return []

        file_ids = sorted({int(h["metadata"].get("kb_file_id", 0)) for h in hits if h.get("metadata")})
        files = await self._kb_repo.get_files_by_ids(file_ids) if file_ids else {}
        today = date.today()

        candidates: list[RetrievedChunk] = []
        seen: set[str] = set()
        for hit in hits:
            meta: dict[str, Any] = hit.get("metadata") or {}
            file_id = int(meta.get("kb_file_id", 0))
            record = files.get(file_id)
            if record is None or record.get("deleted_at"):
                continue  # 文件已删，向量应已被清掉；这里再兜一层
            chunk_id = str(hit["id"])
            if chunk_id in seen:
                continue
            seen.add(chunk_id)

            effective_to = record.get("effective_to")
            expired = bool(effective_to) and effective_to < today
            if expired and not include_expired:
                continue

            page_no = meta.get("page_no")
            candidates.append(
                RetrievedChunk(
                    chunk_id=chunk_id,
                    content=str(hit.get("document") or ""),
                    score=float(hit.get("score", 0.0)),
                    recall_score=float(hit.get("score", 0.0)),
                    kb_file_id=file_id,
                    filename=str(record.get("filename") or ""),
                    page_no=int(page_no) if page_no else None,
                    heading_path=str(meta.get("heading_path") or ""),
                    source_url=record.get("source_url"),
                    expired=expired,
                )
            )

        if not candidates:
            return []

        try:
            scores = await self._reranker.rerank(query, [c.content for c in candidates])
        except DependencyUnavailable as exc:
            logger.warning("rerank_degraded", extra={"extra_fields": {"error": str(exc)}})
            scores = [c.recall_score for c in candidates]

        ranked = sorted(
            (replace(c, score=s) for c, s in zip(candidates, scores)),
            key=lambda c: c.score,
            reverse=True,
        )
        limit = top_n or self._top_n
        return [c for c in ranked if c.score >= self._threshold][:limit]
