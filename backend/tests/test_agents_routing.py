"""Agent 路由与降级测试（不需要真实模型）。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from app.agents.graph import build_graph
from app.agents.nodes import AgentDeps, keyword_intent
from app.agents.state import EDU_DEGRADED_REPLY, NO_EVIDENCE_REPLY
from app.core.errors import DependencyUnavailable, ModelUnavailable


class FakeLLM:
    def __init__(self, label="kb", fail=False):
        self.label = label
        self.fail = fail
        self.calls = 0

    async def chat(self, messages, **kwargs):
        self.calls += 1
        if self.fail:
            raise ModelUnavailable("boom")
        return self.label

    async def stream(self, messages, **kwargs):
        for tok in ["你", "好"]:
            yield tok


@dataclass
class FakeChunk:
    chunk_id: str = "c1"
    content: str = "考试作弊按学校规定给予记过以上处分。"
    score: float = 0.9
    recall_score: float = 0.8
    kb_file_id: int = 1
    filename: str = "考试纪律.pdf"
    page_no: int | None = 2
    heading_path: str = "第二章 考试"
    source_url: str | None = None
    expired: bool = False


class FakeRetriever:
    def __init__(self, chunks=None):
        self.chunks = chunks if chunks is not None else [FakeChunk()]

    async def search(self, query, **kwargs):
        return self.chunks


class FakeSearch:
    def __init__(self, items=None, enabled=True, fail=False):
        self.items = items or []
        self.enabled = enabled
        self.fail = fail

    async def search(self, query):
        if self.fail:
            raise DependencyUnavailable("down")
        return self.items

    @staticmethod
    def cache_key(query):
        return f"k:{query}"


class FakeCache:
    def __init__(self, hit=None):
        self.hit = hit
        self.saved = None

    async def get(self, key, source="anysearch"):
        return self.hit

    async def put(self, key, payload, hours=24, source="anysearch"):
        self.saved = payload


def run(deps, query):
    graph = build_graph(deps)
    return asyncio.run(graph.ainvoke({"query": query, "role": "student", "history": [], "trace": []}))


def make_deps(**kw):
    return AgentDeps(
        llm=kw.get("llm", FakeLLM("kb")),
        retriever=kw.get("retriever", FakeRetriever()),
        search=kw.get("search", FakeSearch()),
        cache=kw.get("cache", FakeCache()),
    )


def test_classify_sets_intent():
    out = run(make_deps(llm=FakeLLM("chitchat")), "你好")
    assert out["intent"] == "chitchat"
    assert out["trace"][0]["node"] == "classify"


def test_kb_intent_retrieves_and_cites():
    out = run(make_deps(llm=FakeLLM("kb")), "考试作弊怎么处理")
    assert out["intent"] == "kb"
    assert len(out["evidence"]) == 1
    assert out["citations"][0]["page_no"] == 2
    assert out["trace"][-1]["node"] == "kb_retrieve"


def test_edu_intent_degrades_not_crash():
    out = run(make_deps(llm=FakeLLM("edu")), "我课表是什么")
    assert out["intent"] == "edu"
    assert out["degraded"] == "edu_pending"
    assert out["evidence"] == []


def test_web_intent_uses_search_results():
    items = [{"title": "关于 2026 年寒假的通知", "url": "https://www.hntou.edu.cn/a.html", "content": "寒假自 1 月 10 日起"}]
    out = run(make_deps(llm=FakeLLM("web"), search=FakeSearch(items)), "最新放假通知")
    assert out["intent"] == "web"
    assert out["evidence"][0]["source_url"].endswith("a.html")


def test_web_without_key_falls_back_to_kb():
    out = run(make_deps(llm=FakeLLM("web"), search=FakeSearch(enabled=False)), "最新放假通知")
    assert out["degraded"] == "search_disabled"
    assert out["evidence"], "应回退到静态库而不是返回空"


def test_web_search_failure_falls_back_to_kb():
    out = run(make_deps(llm=FakeLLM("web"), search=FakeSearch(fail=True)), "最新通知")
    assert out["degraded"] == "search_unavailable"
    assert out["evidence"]


def test_web_uses_cache_when_present():
    cache = FakeCache(hit=[{"title": "缓存命中", "url": "https://x.hntou.edu.cn/1", "content": "内容"}])
    out = run(make_deps(llm=FakeLLM("web"), search=FakeSearch([]), cache=cache), "最新通知")
    assert out["evidence"][0]["filename"] == "缓存命中"
    assert cache.saved is None  # 命中缓存不应重复写


def test_llm_failure_falls_back_to_keywords():
    out = run(make_deps(llm=FakeLLM(fail=True)), "我的成绩什么时候出")
    assert out["intent"] == "edu"  # 关键词兜底识别为教务


@pytest.mark.parametrize(
    "query,expected",
    [
        ("我的课表在哪看", "edu"),
        ("最新通知在哪", "web"),
        ("你好", "chitchat"),
        ("考试作弊怎么处理", "kb"),
        ("帮我写一首诗", "kb"),
    ],
)
def test_keyword_intent(query, expected):
    assert keyword_intent(query) == expected
