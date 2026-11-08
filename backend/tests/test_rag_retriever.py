"""检索层测试：召回顺序、时效过滤、阈值、降级。"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pytest

from app.core.errors import DependencyUnavailable
from app.rag.retriever import Retriever
from app.rag.store import InMemoryVectorStore


class FixedEmbedder:
    async def embed(self, texts):
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]


class ScriptedReranker:
    def __init__(self, scores: list[float]) -> None:
        self.scores = scores
        self.calls = 0

    async def rerank(self, query, passages):
        self.calls += 1
        return self.scores[: len(passages)]


class BrokenReranker:
    async def rerank(self, query, passages):
        raise DependencyUnavailable("重排挂了")


class FakeKbRepo:
    def __init__(self, records: list[dict]) -> None:
        self.records = {int(r["id"]): r for r in records}

    async def get_files_by_ids(self, file_ids):
        return {i: self.records[i] for i in file_ids if i in self.records}


def build_store() -> InMemoryVectorStore:
    store = InMemoryVectorStore()
    store.upsert(
        ids=["c1", "c2", "c3"],
        documents=["学籍管理规定第一条", "考试纪律处罚办法", "食堂营业时间"],
        embeddings=[[1.0, 0.0, 0.0, 0.0], [0.8, 0.6, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]],
        metadatas=[
            {"kb_file_id": 1, "page_no": 3, "heading_path": "第一章 学籍", "tokens": 20},
            {"kb_file_id": 2, "page_no": 0, "heading_path": "第二章 考试", "tokens": 20},
            {"kb_file_id": 3, "page_no": 1, "heading_path": "", "tokens": 20},
        ],
    )
    return store


def make_retriever(store, repo, reranker=None, **kwargs) -> Retriever:
    return Retriever(
        embedder=FixedEmbedder(),
        reranker=reranker or ScriptedReranker([0.9, 0.9, 0.9]),
        store=store,
        kb_repo=repo,
        top_k=kwargs.get("top_k", 20),
        top_n=kwargs.get("top_n", 5),
        threshold=kwargs.get("threshold", 0.35),
    )


def records(expired_file: bool = False) -> list[dict]:
    today = date.today()
    return [
        {
            "id": 1,
            "filename": "学籍管理规定.pdf",
            "source_url": "https://jwc.hntou.edu.cn/a.html",
            "effective_from": today - timedelta(days=30),
            "effective_to": None,
            "deleted_at": None,
        },
        {
            "id": 2,
            "filename": "考试纪律.pdf",
            "source_url": None,
            "effective_from": None,
            "effective_to": today - timedelta(days=1) if expired_file else None,
            "deleted_at": None,
        },
        {
            "id": 3,
            "filename": "后勤通知.pdf",
            "source_url": None,
            "effective_from": None,
            "effective_to": None,
            "deleted_at": None,
        },
    ]


def test_basic_recall_returns_citation_fields():
    retriever = make_retriever(build_store(), FakeKbRepo(records()))
    hits = asyncio.run(retriever.search("学籍"))
    assert hits
    top = hits[0]
    assert top.content
    assert top.filename == "学籍管理规定.pdf"
    assert top.page_no == 3
    assert top.heading_path == "第一章 学籍"
    assert top.source_url == "https://jwc.hntou.edu.cn/a.html"


def test_rerank_reorders_results():
    store = build_store()
    # 让第三名重排后翻到第一
    retriever = make_retriever(store, FakeKbRepo(records()), ScriptedReranker([0.1, 0.2, 0.95]))
    hits = asyncio.run(retriever.search("随便问"))
    assert hits[0].kb_file_id == 3


def test_threshold_filters_low_scores():
    retriever = make_retriever(
        build_store(), FakeKbRepo(records()), ScriptedReranker([0.1, 0.2, 0.9]), threshold=0.5
    )
    hits = asyncio.run(retriever.search("随便问"))
    assert [h.kb_file_id for h in hits] == [3]


def test_expired_document_is_dropped():
    retriever = make_retriever(build_store(), FakeKbRepo(records(expired_file=True)))
    hits = asyncio.run(retriever.search("考试纪律"))
    assert all(h.kb_file_id != 2 for h in hits)


def test_expired_can_be_included_for_admin():
    retriever = make_retriever(build_store(), FakeKbRepo(records(expired_file=True)))
    hits = asyncio.run(retriever.search("考试纪律", include_expired=True))
    assert any(h.kb_file_id == 2 and h.expired for h in hits)


def test_deleted_file_is_skipped():
    recs = records()
    recs[0]["deleted_at"] = "2026-11-01 10:00:00"
    retriever = make_retriever(build_store(), FakeKbRepo(recs))
    hits = asyncio.run(retriever.search("学籍"))
    assert all(h.kb_file_id != 1 for h in hits)


def test_top_n_limits_results():
    retriever = make_retriever(build_store(), FakeKbRepo(records()), top_n=1)
    hits = asyncio.run(retriever.search("学籍"))
    assert len(hits) == 1


def test_reranker_failure_falls_back_to_recall_score():
    retriever = make_retriever(build_store(), FakeKbRepo(records()), BrokenReranker())
    hits = asyncio.run(retriever.search("学籍"))
    assert hits, "重排失败不应导致检索为空"
    assert hits[0].score == pytest.approx(hits[0].recall_score)


def test_empty_query_returns_empty():
    retriever = make_retriever(build_store(), FakeKbRepo(records()))
    assert asyncio.run(retriever.search("   ")) == []


def test_no_vector_hits_returns_empty():
    store = InMemoryVectorStore()
    retriever = make_retriever(store, FakeKbRepo(records()))
    assert asyncio.run(retriever.search("学籍")) == []
