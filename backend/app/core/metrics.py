"""进程内指标：计数器 + 有界延迟样本。

设计取舍
- 单 worker 部署（计划 3.2 第 1 条），指标只在本进程内存里，不引入 Prometheus/Redis。
- 样本用 `deque(maxlen=N)` 限制内存，空闲时占用稳定，符合 P7-01 的“空闲内存稳定”。
- 只从事件循环内调用，不需要额外加锁。
- 暴露给两个出口：`/metrics`（仅本机）与结构化日志里的 `chat_metrics`。
"""

from __future__ import annotations

import math
import time
from collections import Counter, deque
from typing import Any, Iterable

_MAX_SAMPLES = 1000


class Metrics:
    def __init__(self, *, max_samples: int = _MAX_SAMPLES) -> None:
        self._counters: Counter[str] = Counter()
        self._samples: dict[str, deque[float]] = {}
        self._gauges: dict[str, float | int] = {}
        self._max_samples = max_samples
        self.started_at = time.time()

    def inc(self, name: str, value: int = 1) -> None:
        self._counters[name] += value

    def set_gauge(self, name: str, value: float | int) -> None:
        self._gauges[name] = value

    def observe(self, name: str, value: float) -> None:
        bucket = self._samples.get(name)
        if bucket is None:
            bucket = deque(maxlen=self._max_samples)
            self._samples[name] = bucket
        bucket.append(float(value))

    @staticmethod
    def _summary(values: Iterable[float]) -> dict[str, float | int]:
        items = sorted(values)
        if not items:
            return {"count": 0}

        def pct(p: float) -> float:
            if len(items) == 1:
                return round(items[0], 2)
            rank = max(0, min(len(items) - 1, math.ceil(p / 100 * len(items)) - 1))
            return round(items[rank], 2)

        return {
            "count": len(items),
            "min": round(items[0], 2),
            "p50": pct(50),
            "p95": pct(95),
            "p99": pct(99),
            "max": round(items[-1], 2),
            "avg": round(sum(items) / len(items), 2),
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "uptime_s": int(time.time() - self.started_at),
            "counters": dict(sorted(self._counters.items())),
            "timers": {k: self._summary(v) for k, v in sorted(self._samples.items())},
            "gauges": dict(sorted(self._gauges.items())),
        }

    def reset(self) -> None:
        """测试用：清空所有指标。"""
        self._counters.clear()
        self._samples.clear()
        self._gauges.clear()
        self.started_at = time.time()


metrics = Metrics()
