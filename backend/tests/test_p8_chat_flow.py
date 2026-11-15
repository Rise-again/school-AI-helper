"""P8-01：对话编排主流程测试（假图/假模型/假仓储）。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.agents.state import MODEL_DOWN_REPLY, NO_EVIDENCE_REPLY
from app.core.errors import ModelUnavailable
from app.services.chat_service import ChatService


class FakeGraph:
    def __init__(self, state):
        self.state = state

    async def ainvoke(self, inputs):
        return {**inputs, **self.state}


class FakeLLM:
    def __init__(self, tokens=None, error=None, chat_reply=""):
        self.tokens = tokens or []
        self.error = error
        self.chat_reply = chat_reply

    async def stream(self, messages, **kwargs):
        if self.error:
            raise self.error
        for token in self.tokens:
            yield token

    async def chat(self, messages, **kwargs):
        return self.chat_reply


class FakeRepo:
    def __init__(self):
        self.messages = []
        self.citations = []
        self.traces = []
        self.touched = []

    async def get(self, *, user_id, conversation_id):
        return {"id": conversation_id, "user_id": user_id, "title": "t"}

    async def list_messages(self, *, conversation_id, page, size):
        return [], 0

    async def add_message(self, **kwargs):
        self.messages.append(kwargs)
        return 7

    async def add_citations(self, *, message_id, items):
        self.citations.append((message_id, items))

    async def add_trace(self, **kwargs):
        self.traces.append(kwargs)

    async def touch(self, conversation_id):
        self.touched.append(conversation_id)


def make_service(state, llm=None, repo=None):
    settings = SimpleNamespace(rate_limit_per_minute=10)
    return ChatService(
        graph=FakeGraph(state),
        llm=llm or FakeLLM(["答", "案"]),
        conversations=repo or FakeRepo(),
        settings=settings,
    )


def collect(agen):
    async def run():
        return [event async for event in agen]

    return asyncio.run(run())


def test_guest_fixed_reply_path():
    svc = make_service({"direct_reply": "直接回答", "trace": []})
    events = collect(svc.stream_guest(query="q", client_key="v"))
    assert ("delta", {"text": "直接回答"}) in events
    assert events[-1][0] == "done"


def test_guest_no_evidence_path():
    svc = make_service({"intent": "kb", "evidence": [], "trace": []})
    events = collect(svc.stream_guest(query="q", client_key="v"))
    assert ("delta", {"text": NO_EVIDENCE_REPLY}) in events


def test_guest_llm_stream_success():
    state = {
        "intent": "kb",
        "evidence": [{"content": "勤工助学报酬不低于400元/月。", "filename": "a.pdf", "score": 0.9}],
        "citations": [],
        "trace": [{"node": "retrieve", "kb": 1, "web": 0, "kept": 1, "kb_top": 0.9}],
    }
    svc = make_service(state, llm=FakeLLM(["勤工助学报酬不低于400元/月。"]))
    events = collect(svc.stream_guest(query="报酬", client_key="v"))
    assert any(kind == "delta" for kind, _ in events)
    assert events[-1][0] == "done"


def test_guest_model_down_uses_fallback():
    state = {"intent": "chitchat", "evidence": [], "trace": []}
    svc = make_service(state, llm=FakeLLM(error=ModelUnavailable("down")))
    events = collect(svc.stream_guest(query="你好", client_key="v"))
    assert ("delta", {"text": MODEL_DOWN_REPLY}) in events


def test_conversation_stream_persists_message_and_trace():
    repo = FakeRepo()
    state = {
        "direct_reply": "已查到",
        "intent": "edu",
        "citations": [{"kb_file_id": 1, "snippet": "证据"}],
        "trace": [{"node": "edu_query", "status": "ok"}],
    }
    svc = make_service(state, repo=repo)
    events = collect(svc.stream_reply(user_id=1, role="student", conversation_id=5, content="我的课表"))
    assert events[-1][0] == "done"
    assert any(m["role"] == "user" for m in repo.messages)
    assert any(m["role"] == "assistant" for m in repo.messages)
    assert repo.traces and repo.traces[0]["intent"] == "edu"
    assert repo.touched == [5]


def test_conversation_stream_filters_unused_citations():
    repo = FakeRepo()
    state = {
        "intent": "kb",
        "evidence": [
            {"content": "另一条证据。", "filename": "b.pdf", "score": 0.8},
            {"content": "岗位报酬标准见办法。", "filename": "a.pdf", "score": 0.9},
        ],
        "citations": [
            {"kb_file_id": 1, "snippet": "A", "score": 0.9},
            {"kb_file_id": 2, "snippet": "B", "score": 0.8},
        ],
        "trace": [],
    }
    svc = make_service(state, llm=FakeLLM(["岗位报酬标准见办法 [2]。"]), repo=repo)
    events = collect(svc.stream_reply(user_id=1, role="student", conversation_id=5, content="报酬"))
    citations = [data for kind, data in events if kind == "citation"]
    assert citations and citations[0]["items"][0]["kb_file_id"] == 2
