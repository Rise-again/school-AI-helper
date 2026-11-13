"""对话编排：跑状态机 → 组装提示词 → 流式生成 → 落库。

流式期间每 2.5 秒发一次心跳注释：平台代理的 Keep-Alive 只有 4 秒，
模型"思考"停顿超过它就会掐断连接。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, AsyncIterator

from app.agents.state import (
    CHITCHAT_PROMPT,
    EDU_DEGRADED_REPLY,
    NO_EVIDENCE_REPLY,
    PROMPT_VERSION,
    ROLE_TONE,
    SYSTEM_PROMPT,
    format_evidence,
)
from app.core.config import Settings
from app.core.errors import ModelUnavailable, NotFound
from app.core.logging import trace_id_var
from app.integrations.llm_client import LLMClient
from app.repositories.conversations import ConversationRepository

logger = logging.getLogger("campus.chat")

HEARTBEAT_SECONDS = 2.5
HISTORY_TURNS = 8


class ChatService:
    def __init__(
        self,
        *,
        graph,
        llm: LLMClient,
        conversations: ConversationRepository,
        settings: Settings,
    ) -> None:
        self._graph = graph
        self._llm = llm
        self._repo = conversations
        self._settings = settings

    async def _history(self, conversation_id: int) -> list[dict[str, str]]:
        rows, _ = await self._repo.list_messages(conversation_id=conversation_id, page=1, size=200)
        msgs = [{"role": r["role"], "content": r["content"]} for r in rows if r["role"] in ("user", "assistant")]
        return msgs[-HISTORY_TURNS:]

    def _build_messages(self, *, role: str, query: str, state: dict[str, Any], history: list[dict]) -> list[dict]:
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

    async def classify(self, query: str) -> str:
        from app.agents.nodes import classify_intent

        return await classify_intent(self._llm, query)

    async def ensure_owned(self, *, user_id: int, conversation_id: int) -> None:
        conv = await self._repo.get(user_id=user_id, conversation_id=conversation_id)
        if conv is None:
            raise NotFound("会话不存在")

    async def stream_reply(
        self,
        *,
        user_id: int,
        role: str,
        conversation_id: int,
        content: str,
    ) -> AsyncIterator[tuple[str, dict]]:
        conv = await self._repo.get(user_id=user_id, conversation_id=conversation_id)
        if conv is None:
            raise NotFound("会话不存在")

        history = await self._history(conversation_id)
        await self._repo.add_message(
            conversation_id=conversation_id, role="user", content=content, trace_id=trace_id_var.get()
        )
        started = time.perf_counter()

        state: dict[str, Any] = {"query": content, "role": role, "history": history, "trace": []}
        state = await self._graph.ainvoke(state)

        # P3-09 轨迹：节点路径、证据数、降级原因，凭 trace_id 可复盘
        logger.info(
            "agent_trace",
            extra={
                "extra_fields": {
                    "conversation_id": conversation_id,
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

        # 无依据：直接给兜底话术，不调模型（避免编造）
        degraded = state.get("degraded", "")
        if degraded == "edu_pending":
            async for event in self._emit_fixed(conversation_id, EDU_DEGRADED_REPLY, [], started):
                yield event
            return
        if state.get("intent") in ("kb", "web") and not state.get("evidence"):
            async for event in self._emit_fixed(conversation_id, NO_EVIDENCE_REPLY, [], started):
                yield event
            return

        messages = self._build_messages(role=role, query=content, state=state, history=history)
        answer_parts: list[str] = []
        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

        async def produce() -> None:
            try:
                async for token in self._llm.stream(messages):
                    await queue.put(("delta", token))
            except ModelUnavailable as exc:
                await queue.put(("error", str(exc)))
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
                if kind == "error":
                    yield "error", {"message": payload}
                    break
                answer_parts.append(payload)
                yield "delta", {"text": payload}
        finally:
            task.cancel()

        answer = "".join(answer_parts).strip()
        if not answer:
            answer = NO_EVIDENCE_REPLY

        citations = state.get("citations") or []
        # 越界引用告警：模型偶尔会写出不存在的编号，用于发现提示词失效
        bad = [m for m in re.findall(r"\[(\d+)\]", answer) if int(m) > len(citations)]
        if bad:
            logger.warning(
                "citation_out_of_range",
                extra={"extra_fields": {"bad_ids": bad, "evidence": len(citations)}},
            )
        async for event in self._emit_fixed(conversation_id, answer, citations, started, streamed=True):
            yield event

    async def _emit_fixed(
        self,
        conversation_id: int,
        answer: str,
        citations: list[dict],
        started: float,
        *,
        streamed: bool = False,
    ) -> AsyncIterator[tuple[str, dict]]:
        """非流式路径：先落库，再把整段当一次 delta 推出去（前端统一处理）。"""
        latency_ms = int((time.perf_counter() - started) * 1000)
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

        yield "citation", {"items": citations}
        if not streamed:
            yield "delta", {"text": answer}
        yield "done", {"message_id": message_id, "latency_ms": latency_ms, "chars": len(answer)}
