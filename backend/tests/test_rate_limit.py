"""P7 限流与排队：滑动窗口、双维度、队列边界、429 头。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.core.errors import RateLimited
from app.core.metrics import Metrics
from app.core.rate_limit import QueueGate, SlidingWindowLimiter
from app.services.chat_service import ChatService


# ---------- 滑动窗口 ----------
def test_sliding_window_blocks_after_limit():
    limiter = SlidingWindowLimiter(limit=2, window_seconds=60)
    limiter.check("ip:1.2.3.4")
    limiter.check("ip:1.2.3.4")
    with pytest.raises(RateLimited) as exc:
        limiter.check("ip:1.2.3.4")
    assert exc.value.http_status == 429
    assert "Retry-After" in exc.value.headers


def test_sliding_window_keys_are_independent():
    limiter = SlidingWindowLimiter(limit=1, window_seconds=60)
    limiter.check("ip:1.1.1.1")
    limiter.check("ip:2.2.2.2")  # 不同 key 不互相影响
    with pytest.raises(RateLimited):
        limiter.check("ip:1.1.1.1")


def test_windows_expire():
    limiter = SlidingWindowLimiter(limit=1, window_seconds=0.05)
    limiter.check("k")
    import time

    time.sleep(0.06)
    limiter.check("k")  # 窗口过去后应放行


# ---------- 双维度 ----------
def test_user_and_ip_dimensions_are_independent():
    svc = ChatService(
        graph=SimpleNamespace(),
        llm=SimpleNamespace(),
        conversations=SimpleNamespace(),
        settings=SimpleNamespace(rate_limit_per_minute=10),
        user_limiter=SlidingWindowLimiter(limit=2),
        ip_limiter=SlidingWindowLimiter(limit=10),
        guest_limiter=SlidingWindowLimiter(limit=10),
    )
    svc.ensure_allowed(user_id=1, client_key="1.1.1.1")
    svc.ensure_allowed(user_id=1, client_key="1.1.1.1")
    with pytest.raises(RateLimited):
        svc.ensure_allowed(user_id=1, client_key="1.1.1.1")
    # 同一 IP 换个用户，用户维度独立；IP 维度还有余量
    svc.ensure_allowed(user_id=2, client_key="1.1.1.1")


# ---------- 排队 ----------
def test_queue_gate_allows_concurrency_up_to_limit():
    async def run():
        gate = QueueGate(max_concurrent=2, max_queue=1, max_wait_s=1)
        a = await gate.acquire(identity="a")
        b = await gate.acquire(identity="b")
        assert gate.stats()["active"] == 2
        a.release()
        b.release()
        assert gate.stats()["active"] == 0

    asyncio.run(run())


def test_queue_gate_rejects_when_queue_full():
    async def run():
        gate = QueueGate(max_concurrent=1, max_queue=1, max_wait_s=0.5)
        first = await gate.acquire(identity="a")
        waited: list[float] = []

        async def second():
            ticket = await gate.acquire(identity="b")
            waited.append(ticket.waited_ms)
            ticket.release()

        task = asyncio.create_task(second())
        await asyncio.sleep(0.03)  # 让 second 进入队列
        with pytest.raises(RateLimited) as exc:
            await gate.acquire(identity="c")
        assert "Retry-After" in exc.value.headers
        first.release()
        await task
        assert waited and waited[0] > 0

    asyncio.run(run())


def test_queue_gate_times_out():
    async def run():
        gate = QueueGate(max_concurrent=1, max_queue=2, max_wait_s=0.05)
        first = await gate.acquire(identity="a")
        with pytest.raises(RateLimited) as exc:
            await gate.acquire(identity="b")
        assert exc.value.headers.get("Retry-After") == "5"
        first.release()

    asyncio.run(run())


def test_queue_gate_release_is_idempotent():
    async def run():
        gate = QueueGate(max_concurrent=1)
        ticket = await gate.acquire()
        ticket.release()
        ticket.release()
        assert gate.stats()["active"] == 0

    asyncio.run(run())


# ---------- 指标 ----------
def test_metrics_summary_and_counters():
    m = Metrics()
    m.inc("http.requests")
    m.inc("http.requests")
    for value in (100, 200, 300):
        m.observe("latency", value)
    m.record_slow(path="/slow", method="GET", status=200, ms=1200)
    m.record_slow(path="/slower", method="POST", status=500, ms=3500)
    snap = m.snapshot()
    assert snap["counters"]["http.requests"] == 2
    assert snap["timers"]["latency"]["count"] == 3
    assert snap["timers"]["latency"]["p50"] == 200
    assert snap["slow_top"][0]["path"] == "/slower"
    assert snap["slow_top"][0]["ms"] == 3500


# ---------- HTTP 语义 ----------
def test_shared_gateway_detection():
    from app.core.net import is_shared_gateway

    assert is_shared_gateway("172.17.0.1")
    assert is_shared_gateway("127.0.0.1")
    assert is_shared_gateway("unknown")
    assert not is_shared_gateway("203.0.113.9")


def test_rate_limited_response_has_retry_after(client):
    from app.api.deps import get_chat_service

    class Boom:
        def ensure_allowed(self, **kwargs):
            raise RateLimited("请求过多", headers={"Retry-After": "5"})

    client.app.dependency_overrides[get_chat_service] = lambda: Boom()
    resp = client.post("/api/v1/chat/anonymous", json={"content": "你好"})
    assert resp.status_code == 429
    assert resp.headers["Retry-After"] == "5"
    assert resp.json()["code"] == 5001
