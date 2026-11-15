"""P3-04 动态搜索命中率量化：三类典型问题 × 5 条，看引用是否来自官网。

判定：回答出现引用且至少一条 URL 域名以 hntou.edu.cn 结尾 → 命中官网。
用法（服务器可访问的 API）：
    python scripts/evaluate_web.py --api http://127.0.0.1:8080 --user 20230001 --password Student@123
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from urllib.parse import urlparse

CASES = {
    "通知公告": [
        "2026年秋季征兵报名什么时候截止？",
        "学校最近有什么讲座或活动通知？",
        "2026年国庆放假怎么安排？",
        "本学期期末考试安排出来了吗？",
        "学校最近有招聘会吗？",
    ],
    "招生信息": [
        "2026年学校在海南的录取分数线是多少？",
        "学校今年的招生简章在哪里看？",
        "专升本报名条件是什么？",
        "新生奖学金政策今年有变化吗？",
        "学校今年新增了什么专业？",
    ],
    "服务后勤": [
        "图书馆暑假开放时间是什么时候？",
        "校医院周末上班吗？",
        "食堂最近的营业时间有调整吗？",
        "学校班车时刻表在哪里看？",
        "宿舍报修电话是多少？",
    ],
}


def call_json(method: str, url: str, token: str | None = None, body: dict | None = None, timeout: int = 90):
    req = urllib.request.Request(url, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(req, data=data, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def ask(api: str, token: str, question: str) -> dict:
    conv = call_json("POST", f"{api}/api/v1/conversations", token, {"title": "动态搜索评测"})
    cid = conv["data"]["id"]
    req = urllib.request.Request(
        f"{api}/api/v1/conversations/{cid}/messages",
        method="POST",
        data=json.dumps({"content": question}).encode(),
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {token}")
    event = None
    meta, parts, citations = None, [], []
    with urllib.request.urlopen(req, timeout=150) as resp:
        for raw in resp:
            line = raw.decode("utf-8").strip()
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                try:
                    data = json.loads(line[5:].strip())
                except ValueError:
                    continue
                if event == "meta":
                    meta = data
                elif event == "delta":
                    parts.append(data.get("text", ""))
                elif event == "citation":
                    citations = data.get("items") or []
                elif event == "done":
                    break
    call_json("DELETE", f"{api}/api/v1/conversations/{cid}", token)
    answer = "".join(parts)
    domains = []
    for item in citations:
        url = str(item.get("url") or "")
        if url:
            domains.append(urlparse(url).netloc)
    hit = any(d.endswith("hntou.edu.cn") for d in domains)
    return {"answer": answer, "meta": meta or {}, "domains": domains, "hit_official": hit}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8080")
    parser.add_argument("--user", default="20230001")
    parser.add_argument("--password", default="Student@123")
    parser.add_argument("--out", default="/hy-tmp/campus/data/eval_web.json")
    args = parser.parse_args()

    login = call_json("POST", f"{args.api}/api/v1/auth/login", body={"username": args.user, "password": args.password})
    token = login["data"]["access_token"]

    results = []
    for category, questions in CASES.items():
        hits = 0
        for question in questions:
            item = ask(args.api, token, question)
            item.update({"category": category, "question": question})
            results.append(item)
            hits += 1 if item["hit_official"] else 0
            mark = "✓" if item["hit_official"] else "✗"
            print(f"{mark} [{category}] {question} | intent={item['meta'].get('intent')} | {','.join(item['domains'][:3])}", flush=True)
        print(f"— {category}：{hits}/5 命中官网", flush=True)

    total = sum(1 for r in results if r["hit_official"])
    print(f"\n总计 {total}/{len(results)} = {total / len(results):.1%} 命中官网", flush=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"total": len(results), "hits": total, "results": results}, fh, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
