"""P8-01：Agent 路由/检索节点的分支测试。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.agents.nodes import AgentDeps, make_nodes, route_query
from app.core.errors import DependencyUnavailable, ModelUnavailable
from app.rag.retriever import RetrievedChunk


class FakeLLM:
    def __init__(self, reply: str = "", error: Exception | None = None):
        self.reply = reply
        self.error = error

    async def chat(self, *args, **kwargs):
        if self.error:
            raise self.error
        return self.reply


def test_route_query_parses_json_and_falls_back():
    llm = FakeLLM('{"intent":"web","keywords":"招生 简章"}')
    intent, keywords = asyncio.run(route_query(llm, "招生简章在哪"))
    assert intent == "web"
    assert keywords == "招生 简章"

    bad = FakeLLM("不是 JSON")
    intent, keywords = asyncio.run(route_query(bad, "你好"))
    assert intent == "chitchat"
    assert keywords == "你好"

    down = FakeLLM(error=ModelUnavailable("down"))
    intent, keywords = asyncio.run(route_query(down, "最近的放假通知"))
    assert intent == "web"
    assert keywords == "最近的放假通知"


class FakeRetriever:
    def __init__(self, hits=None, error=None):
        self.hits = hits or []
        self.error = error
        self.calls = []

    async def search(self, query: str, *, top_n: int = 5):
        self.calls.append(query)
        if self.error:
            raise self.error
        return list(self.hits)


class FakeSearch:
    enabled = True

    def __init__(self, items=None, error=None):
        self.items = items or []
        self.error = error
        self.calls = []

    def cache_key(self, query):
        return "k"

    async def search(self, query):
        self.calls.append(query)
        if self.error:
            raise self.error
        return list(self.items)


class FakeCache:
    def __init__(self, cached=None, allow=True, error=None):
        self.cached = cached
        self.allow = allow
        self.error = error

    async def get(self, key):
        if self.error:
            raise self.error
        return self.cached

    async def put(self, key, items):
        return None

    async def consume_daily(self, key, limit):
        if self.error:
            raise self.error
        return self.allow


class FakeReranker:
    def __init__(self, scores=None, error=None):
        self.scores = scores or []
        self.error = error

    async def rerank(self, query, passages):
        if self.error:
            raise self.error
        return self.scores or [0.5] * len(passages)


def chunk(**overrides):
    data = dict(
        chunk_id="c1",
        content="勤工助学报酬不低于400元/月。",
        score=0.95,
        recall_score=0.9,
        kb_file_id=1,
        filename="勤工助学管理办法.pdf",
        page_no=1,
        heading_path="第一章",
        source_url=None,
        expired=False,
        topics="work_study",
    )
    data.update(overrides)
    return RetrievedChunk(**data)


def deps(**overrides):
    base = dict(
        llm=FakeLLM(),
        retriever=FakeRetriever([chunk()]),
        reranker=FakeReranker(),
        search=FakeSearch(),
        cache=FakeCache(),
        kb_titles_provider=None,
        edu=None,
        web_max_age_years=2,
    )
    base.update(overrides)
    return AgentDeps(**base)


def retrieve(d, state=None):
    nodes = make_nodes(d)
    state = state or {"query": "勤工助学报酬", "intent": "kb", "keywords": "勤工助学 报酬", "identity": "guest:x"}
    return asyncio.run(nodes["retrieve"](state))


def test_retrieve_kb_sufficient_no_web():
    result = retrieve(deps())
    assert len(result["evidence"]) == 1
    assert result["trace"][-1]["web"] == 0
    assert result["degraded"] == ""


def test_retrieve_kb_empty_falls_back_to_web():
    web = {"title": "通知", "url": "https://x/t20260101_1.html", "content": "这是官网正文。" * 20}
    d = deps(retriever=FakeRetriever([]), search=FakeSearch([web]), reranker=FakeReranker([0.93]))
    result = retrieve(d)
    assert result["evidence"][0]["origin"] == "web"
    assert result["trace"][-1]["web"] == 1


def test_retrieve_kb_unavailable_degrades():
    d = deps(retriever=FakeRetriever(error=DependencyUnavailable("向量库不可用")))
    result = retrieve(d)
    assert result["evidence"] == []
    assert result["degraded"] == "kb_unavailable"


def test_retrieve_cache_unavailable_degrades():
    d = deps(retriever=FakeRetriever([]), cache=FakeCache(error=RuntimeError("db down")))
    result = retrieve(d)
    assert result["degraded"] == "cache_unavailable"


def test_retrieve_quota_exceeded_and_search_failure():
    d = deps(retriever=FakeRetriever([]), cache=FakeCache(allow=False))
    assert retrieve(d)["degraded"] == "search_quota_exceeded"

    d = deps(
        retriever=FakeRetriever([]),
        cache=FakeCache(),
        search=FakeSearch(error=DependencyUnavailable("search down")),
    )
    assert retrieve(d)["degraded"] == "search_unavailable"


def test_retrieve_weak_evidence_refuses():
    weak = chunk(score=0.25, topics="")
    result = retrieve(deps(retriever=FakeRetriever([weak])))
    assert result["evidence"] == []
    assert result["degraded"] == "weak_evidence"


def test_retrieve_topic_miss_forces_web():
    conscription = chunk(score=0.95, topics="conscription")
    web = {"title": "军训", "url": "https://x/t20260101_2.html", "content": "军训正文。" * 20}
    d = deps(
        retriever=FakeRetriever([conscription]),
        search=FakeSearch([web]),
        reranker=FakeReranker([0.91]),
    )
    result = retrieve(d, {"query": "新生军训要带什么", "intent": "kb", "keywords": "新生军训", "identity": "guest:x"})
    assert result["trace"][-1]["topic_miss"] is True
    assert result["evidence"][0]["origin"] == "web"


def test_retrieve_rerank_failure_keeps_scores():
    web = {"title": "通知", "url": "https://x/t20260101_3.html", "content": "官网正文。" * 20}
    d = deps(
        retriever=FakeRetriever([]),
        search=FakeSearch([web]),
        reranker=FakeReranker(error=DependencyUnavailable("rerank down")),
    )
    result = retrieve(d)
    assert result["evidence"] == []  # 联网结果未打分，0 分被阈值筛掉；不崩
