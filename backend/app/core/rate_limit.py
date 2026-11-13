"""进程内限流（单 worker 部署，不引入 Redis）。

按 key（用户 ID 或客户端 IP）做滑动窗口计数；超限抛 RateLimited。
P7 会在此基础上加队列与背压，这里先满足访客匿名提问的基本保护。
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from app.core.errors import RateLimited


class SlidingWindowLimiter:
    def __init__(self, *, limit: int, window_seconds: float = 60.0) -> None:
        self._limit = limit
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        bucket = self._hits[key]
        while bucket and now - bucket[0] > self._window:
            bucket.popleft()
        if len(bucket) >= self._limit:
            raise RateLimited(f"请求过于频繁，每分钟最多 {self._limit} 次")
        bucket.append(now)

    def remaining(self, key: str) -> int:
        now = time.monotonic()
        bucket = self._hits[key]
        while bucket and now - bucket[0] > self._window:
            bucket.popleft()
        return max(0, self._limit - len(bucket))
