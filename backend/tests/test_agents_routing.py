"""Agent 路由与级联检索测试（不需要真实模型）。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from app.agents.graph import build_graph
from app.agents.nodes import AgentDeps, KB_SUFFICIENT_SCORE, keyword_intent
from app.core.errors import DependencyUnavailable, ModelUnavailable


class FakeLLM:
    def __init__(self, label="kb", fail=False):
        self.label = label
        self.fail = fail

    async def chat(self, messages, **kwargs):
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
    def __init__(self, chunks=None, score=None):
        self.chunks = chunks if chunks is not None else [FakeChunk()]
        self.score = score
        self.calls = 0

    async def search(self, query, **kwargs):
        self.calls += 1
        if self.score is None:
            return self.chunks
        return [FakeChunk(chunk_id=f"c{i}", score=self.score) for i in range(len(self.chunks))]


class FakeSearch:
    def __init__(self, items=None, enabled=True, fail=False):
        self.items = items or []
        self.enabled = enabled
        self.fail = fail
        self.calls = 0

    async def search(self, query):
        self.calls += 1
        if self.fail:
            raise DependencyUnavailable("down")
        return self.items

    @staticmethod
    def cache_key(query):
        return f"k:{query}"


class FakeCache:
    def __init__(self, hit=None, quota_ok=True, fail_keys=None):
        self.hit = hit
        self.saved = None
        self.quota_ok = quota_ok
        self.fail_keys = fail_keys or set()
        self.consumed: list[str] = []

    async def get(self, key, source="anysearch"):
        return self.hit

    async def put(self, key, payload, hours=24, source="anysearch"):
        self.saved = payload

    async def consume_daily(self, key, limit):
        self.consumed.append(key)
        if any(k in key for k in self.fail_keys):
            return False
        return self.quota_ok


class FakeReranker:
    """统一打分，便于断言"阈值过滤"；fail=True 时模拟重排服务不可用。"""

    def __init__(self, score=0.9, fail=False):
        self.score = score
        self.fail = fail
        self.calls = 0

    async def rerank(self, query, passages):
        self.calls += 1
        if self.fail:
            raise DependencyUnavailable("down")
        return [self.score for _ in passages]


def make_deps(**kw) -> AgentDeps:
    return AgentDeps(
        llm=kw.get("llm", FakeLLM("kb")),
        retriever=kw.get("retriever", FakeRetriever()),
        reranker=kw.get("reranker", FakeReranker()),
        search=kw.get("search", FakeSearch()),
        cache=kw.get("cache", FakeCache()),
    )


def run(deps: AgentDeps, query: str, identity="user:1"):
    graph = build_graph(deps)
    return asyncio.run(
        graph.ainvoke(
            {"query": query, "role": "student", "identity": identity, "history": [], "trace": []}
        )
    )


# ---------- 路由 ----------
def test_classify_sets_intent():
    out = run(make_deps(llm=FakeLLM("chitchat")), "你好")
    assert out["intent"] == "chitchat"
    assert out["trace"][0]["node"] == "classify"


def test_llm_failure_falls_back_to_keywords():
    out = run(make_deps(llm=FakeLLM(fail=True)), "我的成绩什么时候出")
    assert out["intent"] == "edu"


@pytest.mark.parametrize(
    "query,expected",
    [
        ("我的课表在哪看", "edu"),
        ("最新通知在哪", "web"),
        ("你好", "chitchat"),
        ("考试作弊怎么处理", "kb"),
        ("校内有勤工助学岗位吗", "kb"),
    ],
)
def test_keyword_intent(query, expected):
    assert keyword_intent(query) == expected


# ---------- 级联检索 ----------
def test_kb_strong_hit_skips_web():
    """知识库分数够高时不该花搜索配额。"""
    deps = make_deps(retriever=FakeRetriever(score=0.95), search=FakeSearch([]))
    out = run(deps, "勤工助学怎么申请")
    assert deps.search.calls == 0
    assert out["trace"][-1]["want_web"] is False
    assert len(out["evidence"]) == 1


def test_kb_weak_hit_triggers_web():
    """知识库分数不足时才补联网。"""
    deps = make_deps(
        retriever=FakeRetriever(score=0.5),
        search=FakeSearch([{"title": "最新通知", "url": "https://www.hntou.edu.cn/a.html", "content": "寒假安排"}]),
    )
    out = run(deps, "今年寒假放假安排")
    assert deps.search.calls == 1
    assert out["trace"][-1]["want_web"] is True


def test_web_intent_always_searches_even_if_kb_strong():
    deps = make_deps(
        llm=FakeLLM("web"),
        retriever=FakeRetriever(score=0.99),
        search=FakeSearch([{"title": "公告", "url": "https://zs.hntou.edu.cn/x.html", "content": "最新招生政策"}]),
    )
    run(deps, "今年招生政策有变化吗")
    assert deps.search.calls == 1


def test_irrelevant_results_are_dropped_by_rerank():
    """重排打分低于阈值时全部丢弃 —— 修复"搜到垃圾页当依据"的问题。"""
    deps = make_deps(
        llm=FakeLLM("web"),
        retriever=FakeRetriever(chunks=[]),
        reranker=FakeReranker(score=0.05),
        search=FakeSearch([{"title": "学校首页", "url": "https://www.hntou.edu.cn/", "content": "学校概况"}]),
    )
    out = run(deps, "校内有勤工俭学岗位吗")
    assert out["evidence"] == []
    assert out["citations"] == []


def test_edu_intent_degrades_not_crash():
    out = run(make_deps(llm=FakeLLM("edu")), "我课表是什么")
    assert out["intent"] == "edu"
    assert out["degraded"] == "edu_pending"


def test_web_disabled_falls_back_to_kb():
    deps = make_deps(llm=FakeLLM("web"), search=FakeSearch(enabled=False))
    out = run(deps, "最新放假通知")
    assert out["degraded"] == "search_disabled"
    assert out["evidence"], "应回退到静态库"


def test_web_failure_falls_back_to_kb():
    deps = make_deps(llm=FakeLLM("web"), search=FakeSearch(fail=True))
    out = run(deps, "最新通知")
    assert out["degraded"] == "search_unavailable"
    assert out["evidence"]


def test_web_cache_hit_skips_api_call():
    cache = FakeCache(hit=[{"title": "缓存命中", "url": "https://x.hntou.edu.cn/1", "content": "内容"}])
    deps = make_deps(llm=FakeLLM("web"), search=FakeSearch([]), cache=cache)
    out = run(deps, "最新通知")
    assert deps.search.calls == 0
    assert out["trace"][-1]["web"] == 1


# ---------- 配额 ----------
def test_per_user_quota_blocks_before_global():
    cache = FakeCache(fail_keys={"user:42"})
    deps = make_deps(llm=FakeLLM("web"), search=FakeSearch([]), cache=cache)
    out = run(deps, "最新通知", identity="user:42")
    assert out["degraded"] == "search_quota_exceeded"
    assert cache.consumed == ["anysearch:user:42"], "个人超限时不应再扣全局额度"


def test_global_quota_blocks_when_pool_exhausted():
    cache = FakeCache(fail_keys={"anysearch:global"})
    deps = make_deps(llm=FakeLLM("web"), search=FakeSearch([]), cache=cache)
    out = run(deps, "最新通知")
    assert out["degraded"] == "search_global_quota_exceeded"
    assert cache.consumed == ["anysearch:user:1", "anysearch:global"]


def test_rerank_failure_keeps_recall_scores():
    deps = make_deps(retriever=FakeRetriever(score=0.9), reranker=FakeReranker(fail=True))
    out = run(deps, "考试作弊怎么处理")
    assert out["evidence"], "重排挂了不应清空结果"
    assert out["evidence"][0]["score"] == pytest.approx(0.9)


def test_threshold_constant_is_sane():
    assert 0 < KB_SUFFICIENT_SCORE < 1
