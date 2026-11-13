"""对话编排的边界行为：预算裁剪、降级话术、访客限流。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.state import (
    CONTEXT_TOKEN_BUDGET,
    EDU_DEGRADED_REPLY,
    GUEST_EDU_REPLY,
    MODEL_DOWN_REPLY,
    NO_EVIDENCE_REPLY,
)
from app.core.errors import RateLimited
from app.core.rate_limit import SlidingWindowLimiter
from app.rag.tokens import estimate_tokens
from app.services.chat_service import ChatService


def make_service(limit: int = 2) -> ChatService:
    return ChatService(
        graph=SimpleNamespace(),
        llm=SimpleNamespace(),
        conversations=SimpleNamespace(),
        settings=SimpleNamespace(rate_limit_per_minute=limit),
        guest_limiter=SlidingWindowLimiter(limit=limit, window_seconds=60),
    )


def test_history_trimmed_to_budget():
    long_msg = "学" * 600  # 约 600 token
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": long_msg} for i in range(20)]
    kept = ChatService._trim_history(history)
    total = sum(estimate_tokens(m["content"]) for m in kept)
    assert total <= CONTEXT_TOKEN_BUDGET // 2
    assert len(kept) < len(history)
    assert kept[-1] == history[-1], "应从最新往回保留，最后一条必须留下"


def test_history_short_passes_through():
    history = [{"role": "user", "content": "你好"}, {"role": "assistant", "content": "你好"}]
    assert ChatService._trim_history(history) == history


def test_guest_edu_gets_login_hint():
    svc = make_service()
    assert svc._fixed_reply(role="guest", state={"degraded": "edu_pending"}) == GUEST_EDU_REPLY
    assert svc._fixed_reply(role="student", state={"degraded": "edu_pending"}) == EDU_DEGRADED_REPLY


def test_no_evidence_gets_refusal():
    svc = make_service()
    assert svc._fixed_reply(role="guest", state={"intent": "kb", "evidence": []}) == NO_EVIDENCE_REPLY
    assert svc._fixed_reply(role="student", state={"intent": "web", "evidence": []}) == NO_EVIDENCE_REPLY


def test_chitchat_is_not_treated_as_no_evidence():
    svc = make_service()
    assert svc._fixed_reply(role="guest", state={"intent": "chitchat", "evidence": []}) is None


def test_guest_rate_limit_blocks_after_quota():
    svc = make_service(limit=2)
    svc.ensure_guest_allowed("1.2.3.4")
    svc.ensure_guest_allowed("1.2.3.4")
    with pytest.raises(RateLimited):
        svc.ensure_guest_allowed("1.2.3.4")
    svc.ensure_guest_allowed("5.6.7.8")  # 不同 IP 不受影响


def test_model_down_reply_is_user_facing():
    assert "暂时不可用" in MODEL_DOWN_REPLY
    assert "Traceback" not in MODEL_DOWN_REPLY


def test_only_cited_sources_are_returned():
    """模型引用了 [2]，就只展示第 2 条，其余候选不展示。"""
    svc = make_service()
    cands = [{"snippet": "A"}, {"snippet": "B"}, {"snippet": "C"}]
    assert svc._used_citations("结论在这里 [2]。", cands) == [cands[1]]


def test_multiple_citations_are_sorted_by_index():
    svc = make_service()
    cands = [{"snippet": "A"}, {"snippet": "B"}, {"snippet": "C"}]
    assert svc._used_citations("[3] 与 [1] 都提到", cands) == [cands[0], cands[2]]


def test_no_citation_means_empty_list():
    """模型说"没找到"时不展示任何来源。"""
    svc = make_service()
    cands = [{"snippet": "A"}]
    assert svc._used_citations("我没有找到相关依据。", cands) == []


def test_out_of_range_citation_is_dropped():
    svc = make_service()
    cands = [{"snippet": "A"}]
    assert svc._used_citations("引用不存在的 [9]", cands) == []
