#!/usr/bin/env python3
"""P8-04 端到端 50 题评测（走生产对话链路，含拒答/落地校验）。

用法（服务器）：
    /hy-tmp/campus/venvs/web/bin/python scripts/eval_chat_e2e.py --qa eval/qa_p8_50.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
import uuid
from pathlib import Path

import httpx

REFUSAL_RE = re.compile(r"没有在知识库|没有(直接)?说明|未找到|没有找到|不做推测|无法回答")


def citation_coverage(answer: str) -> float:
    body = re.sub(r"参考：.*", "", answer)
    sentences = [s for s in re.split(r"(?<=[。；！？\n])", body) if len(re.findall(r"[一-龥]", s)) >= 6]
    if not sentences:
        return 1.0
    return sum(1 for s in sentences if re.search(r"\[\d+\]", s)) / len(sentences)


async def ask(client: httpx.AsyncClient, base: str, question: str) -> dict:
    visitor = uuid.uuid4().hex[:16]
    answer = ""
    citations: list[dict] = []
    meta: dict = {}
    started = time.perf_counter()
    async with client.stream(
        "POST",
        base + "/api/v1/chat/anonymous",
        json={"content": question},
        headers={"Cookie": f"visitor_id={visitor}"},
        timeout=180,
    ) as resp:
        resp.raise_for_status()
        event = ""
        async for line in resp.aiter_lines():
            if line.startswith("event: "):
                event = line[7:].strip()
            elif line.startswith("data: "):
                try:
                    data = json.loads(line[6:])
                except ValueError:
                    continue
                if event == "meta":
                    meta = data
                elif event in ("delta", "replace"):
                    answer = data.get("text", "") if event == "replace" else answer + data.get("text", "")
                elif event == "citation":
                    citations = data.get("items") or []
    return {
        "answer": answer,
        "chars": len(answer),
        "seconds": round(time.perf_counter() - started, 2),
        "refused": bool(REFUSAL_RE.search(answer)) and not re.search(r"\[\d+\]", answer),
        "citation_coverage": round(citation_coverage(answer), 3),
        "citation_count": len(citations),
        "degraded": meta.get("degraded", ""),
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qa", default="eval/qa_p8_50.json")
    parser.add_argument("--base", default="http://127.0.0.1:8080")
    parser.add_argument("--out", default="/hy-tmp/campus/data/sft/eval-p8/chat_e2e.json")
    args = parser.parse_args()

    items = json.loads(Path(args.qa).read_text(encoding="utf-8"))
    results = []
    async with httpx.AsyncClient() as client:
        for idx, item in enumerate(items, 1):
            row = await ask(client, args.base, item["question"])
            row.update({"id": item["id"], "question": item["question"], "gold_doc": item.get("gold_doc", "")})
            results.append(row)
            print(f"[{idx}/{len(items)}] {item['id']} refused={row['refused']} degraded={row['degraded']}", flush=True)

    answerable = [r for r in results if r["gold_doc"]]
    outside = [r for r in results if not r["gold_doc"]]
    report = {
        "count": len(results),
        "refusal_rate_outside": round(sum(1 for r in outside if r["refused"]) / max(1, len(outside)), 3),
        "false_refusal_rate_answerable": round(sum(1 for r in answerable if r["refused"]) / max(1, len(answerable)), 3),
        "avg_citation_coverage": round(sum(r["citation_coverage"] for r in results) / len(results), 3),
        "answerable_with_citation": round(sum(1 for r in answerable if r["citation_count"] > 0) / max(1, len(answerable)), 3),
        "avg_seconds": round(sum(r["seconds"] for r in results) / len(results), 2),
    }
    Path(args.out).write_text(json.dumps({"report": report, "results": results}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
