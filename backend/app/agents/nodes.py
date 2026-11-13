"""Agent 各节点：意图分类、静态检索、动态搜索、教务（占位）。

每个节点只读取 state、返回增量字段，不直接改库；持久化由 chat_service 负责。
所有节点都会往 trace 里追加一条记录，供 P3-09 复盘。
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any, Awaitable, Callable

from app.agents.state import INTENT_PROMPT, INTENTS, REWRITE_PROMPT, AgentState, format_context
from app.core.errors import DependencyUnavailable, ModelUnavailable
from app.integrations.anysearch import AnySearchClient
from app.integrations.llm_client import LLMClient
from app.rag.retriever import Retriever
from app.repositories.search_cache import SearchCacheRepository

logger = logging.getLogger("campus.agent")

# 关键词兜底：LLM 分类不可用时用，宁可朴素也别挂
_KEYWORDS = {
    "edu": ("课表", "成绩", "学分", "绩点", "挂科", "选课结果", "我的课", "考试安排"),
    "web": ("最新", "通知", "公告", "今年", "近期", "什么时候", "刚刚", "官网"),
    "chitchat": ("你好", "您好", "你是谁", "在吗", "谢谢", "哈哈"),
}


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
        search: AnySearchClient,
        cache: SearchCacheRepository,
    ) -> None:
        self.llm = llm
        self.retriever = retriever
        self.search = search
        self.cache = cache


async def classify_intent(llm: LLMClient, query: str, history: list[dict[str, str]] | None = None) -> str:
    """LLM 分类，失败时退回关键词规则。带上文是为了让"什么时候发放"这类追问落在正确意图上。"""
    intent = keyword_intent(query)
    ctx = format_context(history or [])
    try:
        label = await llm.chat(
            [{"role": "user", "content": INTENT_PROMPT.format(query=query, context=ctx)}],
            temperature=0.0,
            max_tokens=8,
        )
        cleaned = label.strip().lower().strip("。.：:")
        if cleaned in INTENTS:
            intent = cleaned
    except ModelUnavailable:
        logger.warning("intent_llm_unavailable, fallback to keywords")
    return intent


def _trace(state: AgentState, node: str, **fields: Any) -> list[dict]:
    trace = list(state.get("trace") or [])
    trace.append({"node": node, **fields})
    return trace


def make_nodes(deps: AgentDeps) -> dict[str, Callable[[AgentState], Awaitable[dict]]]:
    async def classify(state: AgentState) -> dict:
        intent = await classify_intent(deps.llm, state["query"], state.get("history"))
        return {"intent": intent, "trace": _trace(state, "classify", intent=intent)}

    async def rewrite_query(query: str, history: list[dict[str, str]] | None = None) -> str:
        """口语问题转检索关键词，并消解指代（"那…"要结合上文）；失败就用原句。"""
        try:
            out = await deps.llm.chat(
                [{"role": "user", "content": REWRITE_PROMPT.format(query=query, context=format_context(history or []))}],
                temperature=0.0,
                max_tokens=24,
            )
        except ModelUnavailable:
            return query
        cleaned = " ".join(out.split())[:40].strip(" 。.：:")
        return cleaned or query

    async def kb_node(state: AgentState) -> dict:
        query = state["query"]
        rewritten = await rewrite_query(query, state.get("history"))
        chunks = await deps.retriever.search(rewritten, top_n=5)
        if not chunks and rewritten != query:
            # 改写没命中时用原句兜底，避免改写把结果改丢
            chunks = await deps.retriever.search(query, top_n=5)
        evidence = [asdict(c) for c in chunks]
        citations = [
            {
                "kb_file_id": c.kb_file_id,
                "chunk_id": c.chunk_id,
                "page_no": c.page_no,
                "url": c.source_url,
                "snippet": c.content[:200],
                "score": c.score,
            }
            for c in chunks
        ]
        return {
            "evidence": evidence,
            "citations": citations,
            "trace": _trace(state, "kb_retrieve", hits=len(evidence), rewritten=rewritten),
        }

    async def web_node(state: AgentState) -> dict:
        query = state["query"]
        items: list[dict] = []
        degraded = ""
        if not deps.search.enabled:
            degraded = "search_disabled"
        else:
            key = deps.search.cache_key(query)
            cached = await deps.cache.get(key)
            if cached is not None:
                items = cached
            else:
                try:
                    items = await deps.search.search(query)
                    if items:
                        await deps.cache.put(key, items)
                except DependencyUnavailable as exc:
                    degraded = "search_unavailable"
                    logger.warning("search_failed", extra={"extra_fields": {"error": str(exc)}})

        if items:
            evidence = [
                {
                    "chunk_id": f"web-{i}",
                    "content": it["content"],
                    "filename": it["title"],
                    "source_url": it["url"],
                    "heading_path": "官网检索",
                    "page_no": None,
                    "score": 1.0,
                }
                for i, it in enumerate(items)
            ]
            citations = [
                {"kb_file_id": None, "chunk_id": e["chunk_id"], "page_no": None,
                 "url": e["source_url"], "snippet": e["content"][:200], "score": 1.0}
                for e in evidence
            ]
            return {
                "evidence": evidence,
                "citations": citations,
                "trace": _trace(state, "web_search", hits=len(evidence)),
            }

        # 搜不到就退回静态库，别把用户扔在空回答里
        fallback = await kb_node(state)
        fallback["degraded"] = degraded or "search_empty"
        fallback["trace"] = _trace(state, "web_search_fallback", reason=fallback["degraded"])
        return fallback

    async def edu_node(state: AgentState) -> dict:
        # P5 未接入前，统一走占位降级，避免 P3 被外部依赖卡住
        return {"evidence": [], "citations": [], "degraded": "edu_pending",
                "trace": _trace(state, "edu_query", status="degraded")}

    return {"classify": classify, "kb": kb_node, "web": web_node, "edu": edu_node}
