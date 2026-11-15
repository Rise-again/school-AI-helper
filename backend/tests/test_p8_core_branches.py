"""P8-01：核心模块的分支补测（加密、指标、状态格式化、排队参数）。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from cryptography.exceptions import InvalidTag

from app.agents.state import format_context, format_evidence, format_terms
from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.metrics import Metrics
from app.core.rate_limit import QueueGate, SlidingWindowLimiter
from app.rag.rerank import HttpRerankerClient


def test_crypto_roundtrip_and_key_errors():
    settings = SimpleNamespace(jwt_secret="x" * 32, edu_cred_key="")
    blob = encrypt_secret(settings, 1, "pw")
    assert decrypt_secret(settings, 1, blob) == "pw"

    keyed = SimpleNamespace(jwt_secret="x" * 32, edu_cred_key="00" * 32)
    assert decrypt_secret(keyed, 1, encrypt_secret(keyed, 1, "pw")) == "pw"

    with pytest.raises(ValueError):
        encrypt_secret(SimpleNamespace(jwt_secret="x" * 32, edu_cred_key="00"), 1, "pw")
    with pytest.raises(ValueError):
        decrypt_secret(settings, 1, None)
    with pytest.raises(ValueError):
        decrypt_secret(settings, 1, b"short")
    with pytest.raises(InvalidTag):
        decrypt_secret(settings, 1, blob[:-1] + bytes([blob[-1] ^ 1]))


def test_metrics_empty_single_and_reset():
    m = Metrics()
    assert m.snapshot()["timers"] == {}
    m.observe("one", 5)
    snap = m.snapshot()
    assert snap["timers"]["one"]["p50"] == 5
    m.set_gauge("rss", 123)
    assert m.snapshot()["gauges"]["rss"] == 123
    m.inc("c", 3)
    m.reset()
    assert m.snapshot()["counters"] == {} and m.snapshot()["gauges"] == {}


def test_state_formatters():
    assert format_terms([]) == ""
    assert format_terms([".pdf"]) == ""
    assert "同名" in format_terms([".pdf", "同名.pdf", "同名.pdf"])
    text = format_terms(["办法.pdf", "办法.pdf", "规定.docx"])
    assert "办法" in text and "规定" in text

    assert format_context([]) == ""
    ctx = format_context(
        [
            {"role": "user", "content": " 你 好 "},
            {"role": "assistant", "content": "你好"},
        ]
    )
    assert "用户：你 好" in ctx or "用户：你 好" in ctx.replace("  ", " ")

    assert format_evidence([]) == "（无）"
    ev = format_evidence(
        [
            {"content": "A"},
            {"content": "B", "filename": "f.pdf", "heading_path": "章", "page_no": 2},
        ]
    )
    assert "未知出处" in ev and "f.pdf·章·第2页" in ev


def test_rate_limit_parameter_validation_and_remaining():
    with pytest.raises(ValueError):
        QueueGate(max_concurrent=0)
    with pytest.raises(ValueError):
        QueueGate(max_queue=-1)
    limiter = SlidingWindowLimiter(limit=2)
    assert limiter.remaining("k") == 2
    limiter.check("k")
    assert limiter.remaining("k") == 1


def test_rerank_ignores_out_of_range_index(monkeypatch):
    client = HttpRerankerClient("http://models")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"results": [{"index": 9, "relevance_score": 0.9}]}

    class FakeHttp:
        async def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(client, "_http", lambda: FakeHttp())
    assert __import__("asyncio").run(client.rerank("q", ["a", "b"])) == [0.0, 0.0]
