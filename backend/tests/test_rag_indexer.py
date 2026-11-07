"""入库编排测试：用假解析器 + 假向量 + 内存向量库，验证编排与幂等。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.core.errors import ValidationFailed
from app.rag.embedding import HashEmbeddingClient
from app.rag.indexer import Indexer
from app.rag.parser import PageText, ParsedDocument
from app.rag.store import InMemoryVectorStore


class FakeParser:
    def __init__(self, pages: list[PageText]) -> None:
        self.pages = pages

    async def parse(self, path: Path) -> ParsedDocument:
        return ParsedDocument(pages=self.pages, channel="markitdown")


class FakeRepo:
    def __init__(self) -> None:
        self.chunks: list[dict] = []

    async def replace_chunks(self, file_id: int, rows: list[dict]) -> None:
        self.chunks = rows


def build(pages: list[PageText], **kwargs):
    store = InMemoryVectorStore()
    repo = FakeRepo()
    indexer = Indexer(
        parser=FakeParser(pages),
        embedder=HashEmbeddingClient(dim=64),
        store=store,
        repo=repo,
        target_tokens=kwargs.get("target_tokens", 200),
        max_tokens=kwargs.get("max_tokens", 240),
        overlap_tokens=kwargs.get("overlap_tokens", 40),
    )
    return indexer, store, repo


BODY = "学生入学后三个月内进行资格复查，复查不合格者按学籍管理规定处理。" * 20


def test_index_writes_chunks_and_vectors():
    indexer, store, repo = build([PageText(None, "# 学籍管理\n\n" + BODY)])
    result = asyncio.run(
        indexer.index_file(file_id=3, path=Path("x.txt"), source_meta={"source_dept": "教务处"})
    )
    assert result.chunk_count == len(repo.chunks) > 1
    assert store.count() == result.chunk_count
    assert all(c["vector_id"].startswith("kb3-c") for c in repo.chunks)
    assert all(v["metadata"]["kb_file_id"] == 3 for v in store.items.values())
    assert all(v["metadata"]["source_dept"] == "教务处" for v in store.items.values())
    assert all(v["metadata"]["heading_path"] == "学籍管理" for v in store.items.values())


def test_reindex_is_idempotent():
    indexer, store, repo = build([PageText(None, BODY)])
    asyncio.run(indexer.index_file(file_id=5, path=Path("x.txt")))
    first = store.count()
    asyncio.run(indexer.index_file(file_id=5, path=Path("x.txt")))
    assert store.count() == first, "重复入库不应产生重复向量"
    assert len(repo.chunks) == first


def test_delete_removes_only_target_file():
    indexer, store, repo = build([PageText(None, BODY)])
    asyncio.run(indexer.index_file(file_id=1, path=Path("a.txt")))
    asyncio.run(indexer.index_file(file_id=2, path=Path("b.txt")))
    store.delete_by_file(1)
    assert all(v["metadata"]["kb_file_id"] == 2 for v in store.items.values())


def test_empty_document_rejected():
    indexer, _, _ = build([])
    with pytest.raises(ValidationFailed):
        asyncio.run(indexer.index_file(file_id=1, path=Path("empty.txt")))


def test_page_number_and_heading_metadata_persist():
    pages = [PageText(1, "# 第一章\n\n第一页正文，关于考试纪律。"), PageText(2, "# 第二章\n\n第二页正文，关于处分。")]
    indexer, store, _ = build(pages)
    asyncio.run(indexer.index_file(file_id=9, path=Path("x.pdf")))
    page_numbers = {v["metadata"]["page_no"] for v in store.items.values()}
    assert page_numbers >= {1}
    assert any(v["metadata"]["heading_path"] in ("第一章", "第二章") for v in store.items.values())
