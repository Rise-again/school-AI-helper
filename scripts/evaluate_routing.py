#!/usr/bin/env python3
"""意图路由评测：跑 25 条用例（五类各 5 条），统计准确率。

用法：
    python scripts/evaluate_routing.py --api http://127.0.0.1:8080 --out docs/11-路由评测.md
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import quote

import httpx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default="eval/routing_cases.json")
    ap.add_argument("--api", default="http://127.0.0.1:8080")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="Admin@12345")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    with httpx.Client(timeout=60) as client:
        token = client.post(
            f"{args.api}/api/v1/auth/login",
            json={"username": args.user, "password": args.password},
        ).json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        rows, hits = [], 0
        per_class = Counter()
        per_class_total = Counter()
        for case in cases:
            got = client.get(
                f"{args.api}/api/v1/rag/intent", params={"q": case["q"]}, headers=headers
            ).json()["data"]["intent"]
            ok = got == case["expect"]
            hits += ok
            per_class_total[case["expect"]] += 1
            per_class[case["expect"]] += ok
            rows.append((case["q"], case["expect"], got, ok))

    total = len(cases)
    lines = ["# 意图路由评测", "", f"- 用例数：{total}", f"- **准确率：{hits / total * 100:.1f}%**（{hits}/{total}）", ""]
    lines.append("| 类别 | 正确/总数 |")
    lines.append("|---|---|")
    for cls in per_class_total:
        lines.append(f"| {cls} | {per_class[cls]}/{per_class_total[cls]} |")
    lines += ["", "| 问题 | 期望 | 实际 | |", "|---|---|---|---|"]
    for q, exp, got, ok in rows:
        lines.append(f"| {q} | {exp} | {got} | {'✓' if ok else '✗'} |")

    text = "\n".join(lines)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"报告写入 {args.out}")
    print("\n".join(lines[:6]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
