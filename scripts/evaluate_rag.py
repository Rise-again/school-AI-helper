#!/usr/bin/env python3
"""RAG 检索评测：给定问答集，逐条调用 /rag/search，统计 Recall@k 与引用命中率。

用法：
    python scripts/evaluate_rag.py --qa eval/qa.json --api http://127.0.0.1:8080 \
        --user admin --password Admin@12345 --top-k 5 --out docs/eval-report.md

问答集格式（JSON 数组）：
    [{"id":"F1","question":"...","gold_doc":"海南热带海洋学院...pdf","note":"可选"}]

没有 gold_doc 的条目不参与召回统计，只统计"是否有召回"和最高分，
用于观察库外问题是否会给出空结果。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import urllib.parse
import urllib.request
from pathlib import Path


def post_json(url: str, payload: dict, token: str | None = None) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def get_json(url: str, token: str) -> dict:
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def login(api: str, user: str, password: str) -> str:
    body = post_json(f"{api}/api/v1/auth/login", {"username": user, "password": password})
    if body.get("code") != 0:
        raise SystemExit(f"登录失败：{body.get('message')}")
    return body["data"]["access_token"]


def search(api: str, token: str, question: str, top_n: int) -> list[dict]:
    q = urllib.parse.quote(question)
    body = get_json(f"{api}/api/v1/rag/search?q={q}&top_n={top_n}", token)
    if body.get("code") != 0:
        raise RuntimeError(body.get("message"))
    return body["data"]["items"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qa", required=True)
    ap.add_argument("--api", default="http://127.0.0.1:8080")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="Admin@12345")
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    items = json.loads(Path(args.qa).read_text(encoding="utf-8"))
    token = login(args.api, args.user, args.password)

    rows, recall1, recallk, scored, empty = [], [], [], [], []
    for item in items:
        q = item["question"]
        gold = item.get("gold_doc") or ""
        hits = search(args.api, token, q, args.top_k)
        top = hits[0]["filename"] if hits else ""
        files = [h["filename"] for h in hits]
        if gold:
            scored.append(item)
            if top == gold:
                recall1.append(item)
            if gold in files:
                recallk.append(item)
        else:
            empty.append(1 if not hits else 0)
        rows.append(
            {
                "id": item.get("id", ""),
                "q": q,
                "gold": gold,
                "top": top,
                "hit": ("✓" if gold and gold in files else ("—" if gold else ("有召回" if hits else "无召回"))),
                "score": round(hits[0]["score"], 3) if hits else 0.0,
                "snippet": (hits[0]["content"][:40].replace("\n", " ") if hits else ""),
            }
        )

    lines = ["# RAG 检索评测报告", ""]
    lines.append(f"- 题目总数：{len(items)}（有标准答案 {len(scored)} 条，库外/无标准答案 {len(empty)} 条）")
    if scored:
        r1 = len(recall1) / len(scored) * 100
        rk = len(recallk) / len(scored) * 100
        lines.append(f"- **Recall@{args.top_k}：{rk:.1f}%**（{len(recallk)}/{len(scored)}）")
        lines.append(f"- **Top-1 命中率：{r1:.1f}%**（{len(recall1)}/{len(scored)}）")
    if empty:
        lines.append(f"- 库外问题给出空结果的比例：{sum(empty) / len(empty) * 100:.1f}%（{sum(empty)}/{len(empty)}）")
    scores = [r["score"] for r in rows if r["score"] > 0]
    if scores:
        lines.append(f"- 命中时最高相关度：中位数 {statistics.median(scores):.3f}，最低 {min(scores):.3f}")
    lines += ["", "| ID | 问题 | 标准文档 | 命中 | Top1 分数 | 首位结果 |", "|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(
            f"| {r['id']} | {r['q'][:38]} | {(r['gold'] or '—')[:30]} | {r['hit']} | {r['score']} | {r['snippet'][:30]} |"
        )

    text = "\n".join(lines)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"报告已写入 {args.out}")
    print(text[:1500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
