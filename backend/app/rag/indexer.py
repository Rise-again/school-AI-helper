"""入库编排：解析 → 切片 → 向量化 → 写向量库 → 写 MySQL。

幂等：同一文件重复入库时先按 kb_file_id 删旧向量再写，不会产生重复命中。
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from app.core.errors import DependencyUnavailable, ValidationFailed
from app.rag.chunker import chunk_pages
from app.rag.embedding import EmbeddingClient
from app.rag.parser import DocumentParser
from app.rag.store import VectorStore
from app.repositories.kb import KbRepository

logger = logging.getLogger("campus.indexer")


@dataclass
class IndexResult:
    chunk_count: int
    channel: str
    warnings: list[str]


class Indexer:
    def __init__(
        self,
        *,
        parser: DocumentParser,
        embedder: EmbeddingClient,
        store: VectorStore,
        repo: KbRepository,
        target_tokens: int = 400,
        max_tokens: int = 480,
        overlap_tokens: int = 80,
    ) -> None:
        self._parser = parser
        self._embedder = embedder
        self._store = store
        self._repo = repo
        self._target = target_tokens
        self._max = max_tokens
        self._overlap = overlap_tokens

    async def index_file(self, *, file_id: int, path: Path, source_meta: dict | None = None) -> IndexResult:
        parsed = await self._parser.parse(path)
        if not parsed.pages:
            raise ValidationFailed("文档没有可用文本（OCR 后仍为空），请确认文件是否损坏或加密")

        chunks = chunk_pages(
            parsed.as_pages(),
            target_tokens=self._target,
            max_tokens=self._max,
            overlap_tokens=self._overlap,
        )
        if not chunks:
            raise ValidationFailed("切片结果为空")

        texts = [c.content for c in chunks]
        vectors = await self._embedder.embed(texts)
        if len(vectors) != len(chunks):
            raise DependencyUnavailable(
                f"向量数量与切片数量不一致：{len(vectors)} vs {len(chunks)}"
            )

        ids = [f"kb{file_id}-c{c.ordinal}" for c in chunks]
        base_meta = dict(source_meta or {})
        metadatas = [
            {
                "kb_file_id": int(file_id),
                "ordinal": c.ordinal,
                "heading_path": c.heading_path or "",
                "page_no": int(c.page_no) if c.page_no is not None else 0,
                "tokens": c.tokens,
                **{
                    k: v
                    for k, v in base_meta.items()
                    if isinstance(v, (str, int, float, bool))
                },
            }
            for c in chunks
        ]

        # 先清旧向量，保证重复入库幂等
        await asyncio.to_thread(self._store.delete_by_file, file_id)
        await asyncio.to_thread(
            self._store.upsert,
            ids=ids,
            documents=texts,
            embeddings=vectors,
            metadatas=metadatas,
        )

        rows = [
            {
                "ordinal": c.ordinal,
                "content": c.content,
                "token_count": c.tokens,
                "vector_id": ids[idx],
                "meta_json": json.dumps(
                    {"heading_path": c.heading_path, "page_no": c.page_no, "tokens": c.tokens},
                    ensure_ascii=False,
                ),
            }
            for idx, c in enumerate(chunks)
        ]
        await self._repo.replace_chunks(file_id, rows)

        logger.info(
            "index_done",
            extra={
                "extra_fields": {
                    "file_id": file_id,
                    "chunks": len(chunks),
                    "channel": parsed.channel,
                }
            },
        )
        return IndexResult(chunk_count=len(chunks), channel=parsed.channel, warnings=parsed.warnings)
