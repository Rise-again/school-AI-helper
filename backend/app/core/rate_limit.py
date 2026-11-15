"""进程内限流与排队（单 worker 部署，不引入 Redis）。

两层保护：
1. `SlidingWindowLimiter`：按 key（用户 ID / 客户端 IP）做滑动窗口计数，超限 429。
2. `QueueGate`：限制同时进行的生成任务数，超出的进入有界队列；队列满或等待超时
   直接 429 + `Retry-After`，避免请求无限堆积把 SSE 连接和内存拖死。

口径（P7 决策）：
- 同时生成上限 = `LLM_MAX_CONCURRENCY`（默认 8，与 vLLM `max-num-seqs` 对齐）；
- 队列最多 3 个，最长等 8 秒；
- 超限只在结构化日志与内存指标里记一笔，不落库、不建表。
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field

from app.core.errors import RateLimited
from app.core.metrics import metrics

logger = logging.getLogger("campus.ratelimit")

RETRY_AFTER_SECONDS = 5


class SlidingWindowLimiter:
    def __init__(self, *, limit: int, window_seconds: float = 60.0) -> None:
        self._limit = limit
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, *, scope: str = "default") -> None:
        now = time.monotonic()
        bucket = self._hits[key]
        while bucket and now - bucket[0] > self._window:
            bucket.popleft()
        if len(bucket) >= self._limit:
            retry_after = max(1, math.ceil(self._window - (now - bucket[0])))
            metrics.inc(f"rate_limit.blocked.{scope}")
            logger.warning(
                "rate_limited",
                extra={"extra_fields": {"scope": scope, "key": key, "limit": self._limit}},
            )
            raise RateLimited(
                f"请求过于频繁，每分钟最多 {self._limit} 次",
                headers={"Retry-After": str(min(retry_after, RETRY_AFTER_SECONDS))},
            )
        bucket.append(now)

    def remaining(self, key: str) -> int:
        now = time.monotonic()
        bucket = self._hits[key]
        while bucket and now - bucket[0] > self._window:
            bucket.popleft()
        return max(0, self._limit - len(bucket))


@dataclass
class QueueTicket:
    """排队凭证：拿到就代表占了一个生成槽位，用完必须 release。"""

    waited_ms: float
    _gate: "QueueGate"
    _released: bool = field(default=False, repr=False)

    def release(self) -> None:
        if not self._released:
            self._released = True
            self._gate._release()


class QueueGate:
    def __init__(
        self,
        *,
        max_concurrent: int = 8,
        max_queue: int = 3,
        max_wait_s: float = 8.0,
        name: str = "chat",
    ) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent 必须 ≥ 1")
        if max_queue < 0:
            raise ValueError("max_queue 不能为负")
        self._sem = asyncio.Semaphore(max_concurrent)
        self._max_concurrent = max_concurrent
        self._max_queue = max_queue
        self._max_wait = max_wait_s
        self._name = name
        self._queued = 0
        self._active = 0
        self._lock = asyncio.Lock()

    async def acquire(self, *, identity: str = "") -> QueueTicket:
        started = time.monotonic()
        async with self._lock:
            # 只有槽位已满时才排队；队列满则立刻拒绝，不占连接
            if self._sem.locked() and self._queued >= self._max_queue:
                metrics.inc(f"{self._name}.queue_rejected")
                logger.warning(
                    "queue_rejected",
                    extra={"extra_fields": {"identity": identity, "queued": self._queued}},
                )
                raise RateLimited(
                    "当前请求较多，请稍后再试",
                    headers={"Retry-After": str(RETRY_AFTER_SECONDS)},
                )
            self._queued += 1

        acquired = False
        try:
            await asyncio.wait_for(self._sem.acquire(), timeout=self._max_wait)
            acquired = True
        except asyncio.TimeoutError:
            metrics.inc(f"{self._name}.queue_timeout")
            logger.warning(
                "queue_timeout",
                extra={"extra_fields": {"identity": identity, "wait_s": self._max_wait}},
            )
            raise RateLimited(
                "仍在排队，请稍后再试",
                headers={"Retry-After": str(RETRY_AFTER_SECONDS)},
            ) from None
        finally:
            async with self._lock:
                self._queued -= 1

        waited_ms = round((time.monotonic() - started) * 1000, 1)
        async with self._lock:
            self._active += 1
        metrics.observe(f"{self._name}.queue_wait_ms", waited_ms)
        if waited_ms >= 50:
            logger.info(
                "queue_waited",
                extra={"extra_fields": {"identity": identity, "waited_ms": waited_ms}},
            )
        return QueueTicket(waited_ms=waited_ms, _gate=self)

    def _release(self) -> None:
        self._sem.release()
        if self._active > 0:
            self._active -= 1

    def stats(self) -> dict[str, int | float]:
        return {
            "active": self._active,
            "queued": self._queued,
            "max_concurrent": self._max_concurrent,
            "max_queue": self._max_queue,
            "max_wait_s": self._max_wait,
        }
