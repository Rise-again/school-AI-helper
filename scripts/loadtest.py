#!/usr/bin/env python3
"""P7-04 阶梯压测：测首字延迟、总时长、错误率与排队。

用法（在服务器 web venv 里跑）：
    /hy-tmp/campus/venvs/web/bin/python scripts/loadtest.py --levels 2,5,6,8,10 --requests 20

说明
- 每个请求用独立 `visitor_id` cookie，避免撞上 10 次/分钟的访客限流；
  要验证限流本身，用 `--reuse-cookie`（所有请求共用一个 cookie）。
- 默认直连 127.0.0.1:8080 测模型能力；`--base-url http://i-2.gpushare.com:44368`
  测平台代理端到端。
- 只依赖 httpx（web venv 已有），不新增依赖。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
import uuid
from dataclasses import dataclass

import httpx

DEFAULT_QUESTIONS = [
    "勤工助学岗位的劳动报酬标准是多少？",
    "国家励志奖学金的申请条件是什么？",
    "新生入学绿色通道怎么办理？",
]


@dataclass
class Sample:
    ok: bool
    status: int
    first_delta_ms: float | None
    total_ms: float
    error: str = ""


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, math.ceil(p / 100 * len(ordered)) - 1))
    return round(ordered[rank], 1)


def summarize(samples: list[Sample], concurrency: int) -> dict:
    ok = [s for s in samples if s.ok]
    first = [s.first_delta_ms for s in ok if s.first_delta_ms is not None]
    total = [s.total_ms for s in ok]
    errors: dict[str, int] = {}
    for s in samples:
        if not s.ok:
            key = s.error or f"http {s.status}"
            errors[key] = errors.get(key, 0) + 1
    return {
        "concurrency": concurrency,
        "requests": len(samples),
        "ok": len(ok),
        "error_rate": round((len(samples) - len(ok)) / len(samples), 4) if samples else 0,
        "errors": errors,
        "first_delta_ms": {
            "p50": percentile(first, 50),
            "p95": percentile(first, 95),
            "p99": percentile(first, 99),
            "max": round(max(first), 1) if first else None,
            "min": round(min(first), 1) if first else None,
        },
        "total_ms": {
            "p50": percentile(total, 50),
            "p95": percentile(total, 95),
            "p99": percentile(total, 99),
            "max": round(max(total), 1) if total else None,
            "min": round(min(total), 1) if total else None,
        },
    }


async def one_request(
    client: httpx.AsyncClient,
    url: str,
    question: str,
    *,
    timeout: float,
    cookie: str,
) -> Sample:
    headers = {
        "Content-Type": "application/json",
        "Cookie": f"visitor_id={cookie}",
    }
    started = time.perf_counter()
    first_delta: float | None = None
    status = 0
    try:
        async with client.stream(
            "POST", url, json={"content": question}, headers=headers, timeout=timeout
        ) as resp:
            status = resp.status_code
            if status != 200:
                await resp.aread()
                return Sample(False, status, None, (time.perf_counter() - started) * 1000, f"http {status}")
            async for line in resp.aiter_lines():
                if line.startswith("event: delta") and first_delta is None:
                    first_delta = (time.perf_counter() - started) * 1000
                elif line.startswith("event: error"):
                    return Sample(False, status, first_delta, (time.perf_counter() - started) * 1000, "sse error")
        return Sample(True, status, first_delta, (time.perf_counter() - started) * 1000)
    except Exception as exc:  # noqa: BLE001 - 压测脚本只需要分类
        return Sample(False, status, first_delta, (time.perf_counter() - started) * 1000, type(exc).__name__)


async def run_level(
    *,
    base_url: str,
    concurrency: int,
    requests: int,
    questions: list[str],
    timeout: float,
    reuse_cookie: bool,
) -> list[Sample]:
    url = base_url.rstrip("/") + "/api/v1/chat/anonymous"
    sem = asyncio.Semaphore(concurrency)
    shared_cookie = uuid.uuid4().hex[:16]
    limits = httpx.Limits(max_connections=max(concurrency * 2, 10), max_keepalive_connections=concurrency)

    async with httpx.AsyncClient(limits=limits) as client:
        async def worker(index: int) -> Sample:
            async with sem:
                cookie = shared_cookie if reuse_cookie else uuid.uuid4().hex[:16]
                return await one_request(
                    client,
                    url,
                    questions[index % len(questions)],
                    timeout=timeout,
                    cookie=cookie,
                )

        return await asyncio.gather(*(worker(i) for i in range(requests)))


async def warmup(base_url: str, timeout: float) -> None:
    url = base_url.rstrip("/") + "/api/v1/chat/anonymous"
    async with httpx.AsyncClient() as client:
        sample = await one_request(client, url, "你好", timeout=timeout, cookie=uuid.uuid4().hex[:16])
    print(f"预热：status={sample.status} first_delta={sample.first_delta_ms} total={sample.total_ms:.0f}ms")


async def main() -> int:
    parser = argparse.ArgumentParser(description="校园智能助手阶梯压测")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--levels", default="2,5,6,8,10", help="并发阶梯，逗号分隔")
    parser.add_argument("--requests", type=int, default=20, help="每档总请求数")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--json-out", default="")
    parser.add_argument("--reuse-cookie", action="store_true", help="所有请求共用一个访客（用于验证限流）")
    parser.add_argument("--no-warmup", action="store_true")
    args = parser.parse_args()

    levels = [int(x) for x in args.levels.split(",") if x.strip()]
    if not args.no_warmup:
        await warmup(args.base_url, args.timeout)

    report = []
    for level in levels:
        print(f"\n=== 并发 {level} / 共 {args.requests} 请求 ===", flush=True)
        samples = await run_level(
            base_url=args.base_url,
            concurrency=level,
            requests=args.requests,
            questions=DEFAULT_QUESTIONS,
            timeout=args.timeout,
            reuse_cookie=args.reuse_cookie,
        )
        summary = summarize(samples, level)
        report.append(summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        print(f"样本：{len(samples)}，成功 {summary['ok']}，错误率 {summary['error_rate']:.1%}")

    if args.json_out:
        payload = {
            "base_url": args.base_url,
            "requests_per_level": args.requests,
            "levels": levels,
            "results": report,
        }
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        print(f"\n已写入 {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
