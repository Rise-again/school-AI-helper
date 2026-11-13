"""Agent 各节点：路由、级联检索、教务（占位）。

检索策略（v2，替代原来的"二选一"）：
1. 永远先做静态 RAG（约 0.2 秒）；
2. 按最高分决定要不要补联网：
   - top1 ≥ 0.80 且用户没明说要最新的 → 只用知识库
   - 否则（含"最新/通知"类意图）→ 联网补充
3. 两路证据合并后**统一重排**，低于阈值的全部丢弃；
4. 联网失败/超配额不影响回答：知识库结果还在，只是少了时效补充。

这样把"路由猜意图"降级为"检索分数说话"，路由判错也不会直接答错。
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any, Awaitable, Callable

from app.agents.state import INTENTS, ROUTER_PROMPT, AgentState, format_context, format_terms
from app.core.errors import DependencyUnavailable, ModelUnavailable
from app.integrations.anysearch import AnySearchClient
from app.integrations.llm_client import LLMClient
from app.rag.rerank import RerankerClient
from app.rag.retriever import Retriever
from app.repositories.search_cache import SearchCacheRepository

logger = logging.getLogger("campus.agent")

# 关键词兜底：LLM 分类不可用时用，宁可朴素也别挂
_KEYWORDS = {
    "edu": ("课表", "成绩", "学分", "绩点", "挂科", "选课结果", "我的课", "考试安排"),
    "web": ("最新", "通知", "公告", "今年", "近期", "刚刚", "官网"),
    "chitchat": ("你好", "您好", "你是谁", "在吗", "谢谢", "哈哈"),
}

# 知识库够用就不联网的分数线。实测同一问题不同问法分数在 0.90–0.99，0.80 留够余量
KB_SUFFICIENT_SCORE = 0.80
# 合并重排后的保留阈值
EVIDENCE_MIN_SCORE = 0.20
# 联网结果正文少于这个字数就不当证据：官网的导航页、栏目页、目录页
# 常常只有"评优评奖… 勤工助学… 联系电话…"这类碎片，重排分能到 0.9，
# 但拿它当依据只会答出正确的废话。
WEB_MIN_CONTENT_CHARS = 80
# 关键词改写后知识库最高分低于这个值，说明改写可能改偏了，用原句再检一次兜底
KB_WEAK_SCORE = 0.50


def keyword_intent(query: str) -> str:
    for intent, words in _KEYWORDS.items():
        if any(w in query for w in words):
            return intent
    return "kb"


class AgentDeps:
    def __init__(
        self,
        *,
        llm: LLMClient,
        retriever: Retriever,
        reranker: RerankerClient,
        search: AnySearchClient,
        cache: SearchCacheRepository,
        search_daily_quota: int = 1800,
        search_user_daily_quota: int = 60,
        kb_titles_provider: Callable[[], Awaitable[list[str]]] | None = None,
    ) -> None:
        self.llm = llm
        self.retriever = retriever
        self.reranker = reranker
        self.search = search
        self.cache = cache
        self.search_daily_quota = search_daily_quota
        self.search_user_daily_quota = search_user_daily_quota
        self.kb_titles_provider = kb_titles_provider


async def route_query(
    llm: LLMClient,
    query: str,
    history: list[dict[str, str]] | None = None,
    terms: list[str] | None = None,
) -> tuple[str, str]:
    """一次调用同时得到意图与检索关键词（分类+改写合并，省一次模型往返）。

    terms 是知识库文件名，作为"官方用词参考"注入提示词——
    不写死同义词表，让模型结合真实语料现场判断该换成什么说法。
    """
    import json as _json

    intent = keyword_intent(query)
    keywords = query
    ctx = format_context(history or [])
    terms_block = format_terms(terms or [])
    try:
        raw = await llm.chat(
            [{"role": "user", "content": ROUTER_PROMPT.format(query=query, context=ctx, terms=terms_block)}],
            temperature=0.0,
            max_tokens=64,
        )
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`").split("\n", 1)[-1]
        data = _json.loads(text[text.index("{"): text.rindex("}") + 1])
        label = str(data.get("intent", "")).lower()
        if label in INTENTS:
            intent = label
        kw = " ".join(str(data.get("keywords", "")).split())[:40].strip("。.")
        if kw:
            keywords = kw
    except ModelUnavailable:
        logger.warning("router_llm_unavailable, fallback to keywords")
    except (ValueError, KeyError):
        logger.warning("router_output_unparsable, fallback to keywords")
    return intent, keywords


async def classify_intent(
    llm: LLMClient,
    query: str,
    history: list[dict[str, str]] | None = None,
    terms: list[str] | None = None,
) -> str:
    return (await route_query(llm, query, history, terms))[0]


def _trace(state: AgentState, node: str, **fields: Any) -> list[dict]:
    trace = list(state.get("trace") or [])
    trace.append({"node": node, **fields})
    return trace


def make_nodes(deps: AgentDeps) -> dict[str, Callable[[AgentState], Awaitable[dict]]]:
    async def classify(state: AgentState) -> dict:
        terms: list[str] = []
        if deps.kb_titles_provider is not None:
            try:
                terms = await deps.kb_titles_provider()
            except Exception:  # noqa: BLE001 - 取术语失败不影响主流程
                logger.warning("kb_titles_unavailable")
        intent, keywords = await route_query(
            deps.llm, state["query"], state.get("history"), terms
        )
        return {
            "intent": intent,
            "keywords": keywords,
            "trace": _trace(state, "classify", intent=intent, keywords=keywords),
        }

    async def _kb_search(query: str, keywords: str) -> list[dict[str, Any]]:
        """静态检索：先用改写后的关键词；关键词检索不到像样结果时用原句兜底。

        只判断"是否为空"不够——关键词改偏时仍会返回一堆 0.1 分的碎片，
        原句反而能查到正确片段，所以以最高分为准再补捡一次。
        """
        hits = await deps.retriever.search(keywords, top_n=5)
        weak = max((c.score for c in hits), default=0.0) < KB_WEAK_SCORE
        if keywords != query and weak:
            extra = await deps.retriever.search(query, top_n=5)
            merged = {c.chunk_id: c for c in hits}
            for c in extra:
                prev = merged.get(c.chunk_id)
                if prev is None or c.score > prev.score:
                    merged[c.chunk_id] = c
            hits = sorted(merged.values(), key=lambda c: c.score, reverse=True)
        return [
            {
                "chunk_id": c.chunk_id,
                "content": c.content,
                "filename": c.filename,
                "source_url": c.source_url,
                "heading_path": c.heading_path,
                "page_no": c.page_no,
                "kb_file_id": c.kb_file_id,
                "score": c.score,
                "origin": "kb",
            }
            for c in hits
        ]

    async def _web_search(state: AgentState, query: str) -> tuple[list[dict[str, Any]], str]:
        """联网检索；返回 (证据, 降级原因)。"""
        if not deps.search.enabled:
            return [], "search_disabled"

        key = deps.search.cache_key(query)
        cached = await deps.cache.get(key)
        if cached is not None:
            return _web_items(cached), ""

        identity = state.get("identity") or "guest:unknown"
        # 先扣个人额度再扣全局：个人超额时不该白白消耗全局池
        user_ok = await deps.cache.consume_daily(f"anysearch:{identity}", deps.search_user_daily_quota)
        global_ok = False
        if user_ok:
            global_ok = await deps.cache.consume_daily("anysearch:global", deps.search_daily_quota)
        if not user_ok or not global_ok:
            logger.warning(
                "search_quota_exceeded",
                extra={"extra_fields": {"identity": identity}},
            )
            return [], "search_quota_exceeded" if not user_ok else "search_global_quota_exceeded"

        try:
            items = await deps.search.search(query)
        except DependencyUnavailable as exc:
            logger.warning("search_failed", extra={"extra_fields": {"error": str(exc)}})
            return [], "search_unavailable"
        if items:
            await deps.cache.put(key, items)
        return _web_items(items), ""

    @staticmethod
    def _web_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        kept = []
        for it in items:
            text = " ".join(str(it.get("content") or "").split())
            # 长度够 + 至少有一个完整句子，才算"能当依据的网页正文"
            if len(text) >= WEB_MIN_CONTENT_CHARS and "。" in text:
                kept.append(it)
        if len(kept) < len(items):
            logger.info(
                "web_items_unusable_dropped",
                extra={"extra_fields": {"total": len(items), "kept": len(kept)}},
            )
        return [
            {
                "chunk_id": f"web-{i}",
                "content": it["content"],
                "filename": it["title"],
                "source_url": it["url"],
                "heading_path": "官网检索",
                "page_no": None,
                "kb_file_id": None,
                "score": 0.0,  # 未打分，交给重排
                "origin": "web",
            }
            for i, it in enumerate(kept)
        ]

    async def retrieve(state: AgentState) -> dict:
        """级联检索：先 RAG，不够再联网，合并后统一重排。"""
        query = state["query"]
        intent = state.get("intent", "kb")
        keywords = state.get("keywords") or query

        kb_items = await _kb_search(query, keywords)
        kb_top = max((e["score"] for e in kb_items), default=0.0)

        # 用户明确要"最新/通知"时总补联网；否则知识库分数够就不花配额
        want_web = intent == "web" or kb_top < KB_SUFFICIENT_SCORE
        web_items: list[dict[str, Any]] = []
        degraded = ""
        if want_web:
            web_items, degraded = await _web_search(state, keywords)

        # 知识库结果已经用「改写后的关键词」重排过，不能再拿原句重排一遍：
        # 口语长句（"一般都做些什么工作"）对同一片段只能打 0.1–0.2 分，会把正确结果全部筛掉。
        # 这里只对联网结果补打分，KB 沿用检索阶段（关键词）的分数。
        if web_items:
            try:
                web_scores = await deps.reranker.rerank(keywords, [e["content"] for e in web_items])
                web_items = [
                    dict(e, score=round(float(s), 4)) for e, s in zip(web_items, web_scores)
                ]
            except DependencyUnavailable as exc:
                logger.warning("rerank_failed", extra={"extra_fields": {"error": str(exc)}})

        merged = kb_items + web_items
        if not merged:
            return {
                "evidence": [],
                "citations": [],
                "degraded": degraded or "no_evidence",
                "trace": _trace(state, "retrieve", kb=0, web=0, kb_top=round(kb_top, 3)),
            }

        ranked = sorted(merged, key=lambda e: e["score"], reverse=True)
        kept = [e for e in ranked if e["score"] >= EVIDENCE_MIN_SCORE][:3]  # 证据越多越容易漏标

        citations = [
            {
                "kb_file_id": e["kb_file_id"],
                "chunk_id": e["chunk_id"],
                "page_no": e["page_no"],
                "url": e["source_url"],
                "snippet": e["content"][:200],
                "score": e["score"],
            }
            for e in kept
        ]
        return {
            "evidence": kept,
            "citations": citations,
            "degraded": degraded,
            "trace": _trace(
                state,
                "retrieve",
                kb=len(kb_items),
                web=len(web_items),
                kb_top=round(kb_top, 3),
                kept=len(kept),
                want_web=want_web,
            ),
        }

    async def edu_node(state: AgentState) -> dict:
        # P5 未接入前，统一走占位降级，避免 P3 被外部依赖卡住
        return {
            "evidence": [],
            "citations": [],
            "degraded": "edu_pending",
            "trace": _trace(state, "edu_query", status="degraded"),
        }

    return {"classify": classify, "retrieve": retrieve, "edu": edu_node}
