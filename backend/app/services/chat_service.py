"""对话编排：跑状态机 → 组装提示词 → 流式生成 → 落库。

三条硬要求：
1. 流式期间每 2.5 秒发心跳：平台代理 Keep-Alive 只有 4 秒。
2. 客户端断线时，已生成的内容必须落库（用 shield 保护最后的写入）。
3. 模型不可用时不抛 500、不回 error 事件，而是给降级话术。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from typing import Any, AsyncIterator

from app.agents.state import (
    CHITCHAT_PROMPT,
    CONTEXT_TOKEN_BUDGET,
    EDU_DEGRADED_REPLY,
    GUEST_EDU_REPLY,
    MODEL_DOWN_REPLY,
    NO_EVIDENCE_REPLY,
    PROMPT_VERSION,
    REPAIR_PROMPT,
    ROLE_TONE,
    SYSTEM_PROMPT,
    format_evidence,
)
from app.core.config import Settings
from app.core.errors import ModelUnavailable, NotFound, RateLimited
from app.core.logging import trace_id_var
from app.core.rate_limit import SlidingWindowLimiter
from app.integrations.llm_client import LLMClient
from app.rag.tokens import estimate_tokens
from app.repositories.conversations import ConversationRepository
from app.services.grounding import audit_answer, drop_violations, violation_brief

logger = logging.getLogger("campus.chat")

HEARTBEAT_SECONDS = 2.5
HISTORY_TURNS = 8


def _has_substance(text: str) -> bool:
    """删句/重写之后不能只剩"[2]""参考：[1]"这类空壳。

    只要求去掉标注与参考行后还剩两个字，避免把"每周不超过20小时 [1]。"这种短答误判为空。
    """
    body = re.sub(r"参考：[^\n]*", "", text or "")
    body = re.sub(r"\[\d+\]", "", body)
    return len(re.findall(r"[一-龥]", body)) >= 2


_NOT_FOUND_RE = re.compile(r"(没有|未)(找到|直接说明|明确说明|提及)")


def _strip_marks_if_not_found(text: str) -> str:
    """回答本身就说"资料没写"时，编号和参考行只会造成误解，一并去掉。"""
    if not _NOT_FOUND_RE.search(text[:40]):
        return text
    text = re.sub(r"\n?参考：[^\n]*", "", text)
    text = re.sub(r"\[\d+\]", "", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


class ChatService:
    def __init__(
        self,
        *,
        graph,
        llm: LLMClient,
        conversations: ConversationRepository,
        settings: Settings,
        guest_limiter: SlidingWindowLimiter | None = None,
    ) -> None:
        self._graph = graph
        self._llm = llm
        self._repo = conversations
        self._settings = settings
        self._guest_limiter = guest_limiter or SlidingWindowLimiter(
            limit=settings.rate_limit_per_minute
        )

    # ---------------- 公共 ----------------
    async def classify(self, query: str, history: list[dict[str, str]] | None = None) -> str:
        from app.agents.nodes import classify_intent

        return await classify_intent(self._llm, query, history)

    async def ensure_owned(self, *, user_id: int, conversation_id: int) -> None:
        conv = await self._repo.get(user_id=user_id, conversation_id=conversation_id)
        if conv is None:
            raise NotFound("会话不存在")

    # ---------------- 登录用户 ----------------
    async def stream_reply(
        self,
        *,
        user_id: int,
        role: str,
        conversation_id: int,
        content: str,
    ) -> AsyncIterator[tuple[str, dict]]:
        await self.ensure_owned(user_id=user_id, conversation_id=conversation_id)
        history = await self._history(conversation_id)
        await self._repo.add_message(
            conversation_id=conversation_id, role="user", content=content, trace_id=trace_id_var.get()
        )
        async for event in self._generate(
            query=content,
            role=role,
            history=history,
            conversation_id=conversation_id,
            identity=f"user:{user_id}",
        ):
            yield event

    # ---------------- 访客（匿名） ----------------
    async def stream_guest(
        self, *, query: str, client_key: str
    ) -> AsyncIterator[tuple[str, dict]]:
        # 配额已在 ensure_guest_allowed 扣减，这里不再重复计数
        async for event in self._generate(
            query=query, role="guest", history=[], conversation_id=None, identity=f"guest:{client_key}"
        ):
            yield event

    def ensure_guest_allowed(self, client_key: str) -> None:
        """建流前扣减配额并校验，超限抛 RateLimited（429）。"""
        self._guest_limiter.check(client_key)

    def guest_remaining(self, client_key: str) -> int:
        return self._guest_limiter.remaining(client_key)

    # ---------------- 核心 ----------------
    async def _history(self, conversation_id: int) -> list[dict[str, str]]:
        rows, _ = await self._repo.list_messages(conversation_id=conversation_id, page=1, size=200)
        msgs = [
            {"role": r["role"], "content": r["content"]}
            for r in rows
            if r["role"] in ("user", "assistant")
        ]
        return self._trim_history(msgs)

    @staticmethod
    def _trim_history(history: list[dict[str, str]]) -> list[dict[str, str]]:
        """按 token 预算从旧到新裁掉，保证超长会话不撑爆上下文。"""
        kept: list[dict[str, str]] = []
        total = 0
        for msg in reversed(history[-HISTORY_TURNS * 2 :]):
            cost = estimate_tokens(msg["content"]) + 4
            if total + cost > CONTEXT_TOKEN_BUDGET // 2:  # 一半预算给历史，一半给证据与回答
                break
            kept.append(msg)
            total += cost
        return list(reversed(kept))

    def _build_messages(
        self, *, role: str, query: str, state: dict[str, Any], history: list[dict[str, str]]
    ) -> list[dict]:
        intent = state.get("intent", "kb")
        evidence = state.get("evidence") or []
        if intent in ("chitchat", "unknown") or not evidence:
            return [{"role": "user", "content": CHITCHAT_PROMPT.format(query=query)}]
        system = SYSTEM_PROMPT.format(
            version=PROMPT_VERSION,
            role_tone=ROLE_TONE.get(role, ROLE_TONE["guest"]),
            evidence=format_evidence(evidence),
            evidence_count=len(evidence),
        )
        return [{"role": "system", "content": system}, *history, {"role": "user", "content": query}]

    async def _generate(
        self,
        *,
        query: str,
        role: str,
        history: list[dict[str, str]],
        conversation_id: int | None,
        identity: str,
    ) -> AsyncIterator[tuple[str, dict]]:
        started = time.perf_counter()
        state: dict[str, Any] = {
            "query": query,
            "role": role,
            "identity": identity,
            "history": history,
            "trace": [],
        }
        state = await self._graph.ainvoke(state)

        logger.info(
            "agent_trace",
            extra={
                "extra_fields": {
                    "conversation_id": conversation_id,
                    "role": role,
                    "intent": state.get("intent", ""),
                    "evidence": len(state.get("evidence") or []),
                    "degraded": state.get("degraded", ""),
                    "nodes": [t.get("node") for t in (state.get("trace") or [])],
                    "prompt_version": PROMPT_VERSION,
                }
            },
        )

        yield "meta", {
            "intent": state.get("intent", ""),
            "evidence_count": len(state.get("evidence") or []),
            "degraded": state.get("degraded", ""),
            "prompt_version": PROMPT_VERSION,
        }

        # 固定回复路径：不调模型，直接落库并返回
        fixed = self._fixed_reply(role=role, state=state)
        if fixed is not None:
            async for event in self._finish(conversation_id, fixed, [], started, emit_text=True):
                yield event
            return

        messages = self._build_messages(role=role, query=query, state=state, history=history)
        async for event in self._stream_llm(
            messages=messages, conversation_id=conversation_id, state=state, started=started
        ):
            yield event

    @staticmethod
    def _fixed_reply(*, role: str, state: dict[str, Any]) -> str | None:
        degraded = state.get("degraded", "")
        intent = state.get("intent", "")
        if degraded == "edu_pending":
            return GUEST_EDU_REPLY if role == "guest" else EDU_DEGRADED_REPLY
        if intent in ("kb", "web") and not state.get("evidence"):
            return NO_EVIDENCE_REPLY
        return None

    async def _stream_llm(
        self,
        *,
        messages: list[dict],
        conversation_id: int | None,
        state: dict[str, Any],
        started: float,
    ) -> AsyncIterator[tuple[str, dict]]:
        parts: list[str] = []
        failed = False
        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

        async def produce() -> None:
            try:
                async for token in self._llm.stream(messages):
                    await queue.put(("delta", token))
            except ModelUnavailable as exc:
                logger.warning("llm_stream_failed", extra={"extra_fields": {"error": str(exc)}})
                await queue.put(("down", None))
            finally:
                await queue.put(("eof", None))

        task = asyncio.create_task(produce())
        try:
            while True:
                try:
                    kind, payload = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    yield "ping", {}
                    continue
                if kind == "eof":
                    break
                if kind == "down":
                    failed = True
                    break
                parts.append(payload)
                yield "delta", {"text": payload}
        except (asyncio.CancelledError, GeneratorExit):
            # 客户端断开：把已经生成的部分落库，否则用户刷新后看不到这条回答
            partial = "".join(parts).strip()
            if conversation_id is not None and partial:
                latency_ms = int((time.perf_counter() - started) * 1000)
                with contextlib.suppress(Exception):
                    await asyncio.shield(
                        self._persist(
                            conversation_id,
                            partial,
                            self._used_citations(partial, state.get("citations") or []),
                            latency_ms,
                        )
                    )
                logger.info(
                    "stream_aborted_persisted",
                    extra={"extra_fields": {"chars": len(partial), "conversation_id": conversation_id}},
                )
            raise
        finally:
            task.cancel()

        answer = "".join(parts).strip()
        if failed and not answer:
            # 一个字都没生成就挂了：给降级话术，而不是 error 事件
            async for event in self._finish(conversation_id, MODEL_DOWN_REPLY, [], started, emit_text=True):
                yield event
            return
        if not answer:
            answer = NO_EVIDENCE_REPLY

        # 落地校验：回答里不能出现资料中没有的具体内容
        evidence = state.get("evidence") or []
        audited = _strip_marks_if_not_found(await self._ground(answer, evidence))
        if audited != answer:
            logger.info(
                "answer_grounded",
                extra={"extra_fields": {"before": answer[:120], "after": audited[:120]}},
            )
            answer = audited
            yield "replace", {"text": answer}

        all_citations = state.get("citations") or []
        citations = self._used_citations(answer, all_citations)

        async for event in self._finish(conversation_id, answer, citations, started, emit_text=False):
            yield event

    async def _ground(self, answer: str, evidence: list[dict]) -> str:
        """落地校验：回答里出现的具体名称/材料/数字，必须在资料原文里找得到。

        违规时先让模型按清单重写一次；重写后仍违规，直接删掉涉事句子。
        宁可少说，也不把捏造的具体信息交给用户。
        """
        violations = audit_answer(answer, evidence)
        if not violations:
            return answer
        logger.warning(
            "answer_ungrounded",
            extra={"extra_fields": {"spans": violation_brief(violations)[:200]}},
        )
        repaired = await self._repair(answer, evidence, violations)
        if not _has_substance(repaired):
            # 重写把话删干净了（只剩"[2]"这种），退回原始回答做删句兜底
            repaired = drop_violations(answer, violations)
        rest = audit_answer(repaired, evidence)
        if rest:
            logger.warning(
                "answer_ungrounded_after_repair",
                extra={"extra_fields": {"spans": violation_brief(rest)[:200]}},
            )
            repaired = drop_violations(repaired, rest)
        if not _has_substance(repaired):
            return NO_EVIDENCE_REPLY
        return repaired

    async def _repair(
        self, answer: str, evidence: list[dict], violations: list
    ) -> str:
        messages = [
            {"role": "system", "content": REPAIR_PROMPT.format(bad=violation_brief(violations))},
            {
                "role": "user",
                "content": f"【参考资料】\n{format_evidence(evidence)}\n\n【原回答】\n{answer}",
            },
        ]
        try:
            fixed = await self._llm.chat(messages, temperature=0.1, max_tokens=600)
        except ModelUnavailable:
            return drop_violations(answer, violations)
        return (fixed or "").strip() or drop_violations(answer, violations)

    @staticmethod
    def _used_citations(answer: str, citations: list[dict]) -> list[dict]:
        """只返回回答里真正引用到的条目。

        模型可能在大量候选里只用了 [2][5]；也常常在"没找到"时一条都没用。
        按回答里出现的编号过滤，避免把不相关内容当成"出处"展示。
        """
        # 回答本身就说"资料没写"时，挂三张来源卡片只会让人误解
        if re.search(r"(没有|未)(找到|直接说明|明确说明|提及)", answer[:40]):
            return []
        used = sorted({int(n) for n in re.findall(r"\[(\d+)\]", answer) if 1 <= int(n) <= len(citations)})
        invalid = [n for n in re.findall(r"\[(\d+)\]", answer) if int(n) > len(citations)]
        if invalid:
            logger.warning(
                "citation_out_of_range",
                extra={"extra_fields": {"bad_ids": invalid, "candidates": len(citations)}},
            )
        return [citations[i - 1] for i in used]

    async def _finish(
        self,
        conversation_id: int | None,
        answer: str,
        citations: list[dict],
        started: float,
        *,
        emit_text: bool,
    ) -> AsyncIterator[tuple[str, dict]]:
        latency_ms = int((time.perf_counter() - started) * 1000)

        if conversation_id is not None:
            # 客户端断线时生成器会被取消，用 shield 保证写入完成
            with contextlib.suppress(Exception):
                await asyncio.shield(self._persist(conversation_id, answer, citations, latency_ms))

        if citations:
            yield "citation", {"items": citations}
        if emit_text:
            yield "delta", {"text": answer}
        yield "done", {"latency_ms": latency_ms, "chars": len(answer)}

    async def _persist(
        self, conversation_id: int, answer: str, citations: list[dict], latency_ms: int
    ) -> None:
        message_id = await self._repo.add_message(
            conversation_id=conversation_id,
            role="assistant",
            content=answer,
            latency_ms=latency_ms,
            trace_id=trace_id_var.get(),
        )
        if citations:
            await self._repo.add_citations(message_id=message_id, items=citations)
        await self._repo.touch(conversation_id)


__all__ = ["ChatService", "RateLimited"]
