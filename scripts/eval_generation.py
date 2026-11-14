"""P4-07 基座 vs 微调对比评测（生成层）。

同一 60 条评测集、同一检索证据、同一提示词，只换模型（基座 / LoRA），
输出逐题对比与自动指标：编造校验违规、标注覆盖率、拒答率、长度、耗时。

用法（服务器，vLLM 已加载基座 + adapter）：
    /hy-tmp/campus/venvs/web/bin/python scripts/eval_generation.py \
        --adapter-model campus-lora --out /hy-tmp/campus/data/sft/eval
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

import httpx  # noqa: E402

from app.agents.state import ROLE_TONE, SYSTEM_PROMPT, format_evidence  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.services.grounding import audit_answer  # noqa: E402

PROMPT_VERSION = "p4-eval"
REFUSAL_RE = re.compile(r"没有(直接)?说明|未找到|没有找到|不做推测|无法回答")


def citation_coverage(answer: str) -> float:
    body = re.sub(r"参考：.*", "", answer)
    sentences = [s for s in re.split(r"(?<=[。；！？\n])", body) if len(re.findall(r"[一-龥]", s)) >= 6]
    if not sentences:
        return 1.0
    return sum(1 for s in sentences if re.search(r"\[\d+\]", s)) / len(sentences)


async def admin_token(client: httpx.AsyncClient, base: str) -> str:
    resp = await client.post(f"{base}/api/v1/auth/login", json={"username": "admin", "password": "Admin@12345"})
    resp.raise_for_status()
    return resp.json()["data"]["access_token"]


async def retrieve(client: httpx.AsyncClient, base: str, token: str, question: str, top_n: int = 5) -> list[dict]:
    resp = await client.get(
        f"{base}/api/v1/rag/search",
        params={"q": question, "top_n": top_n},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    return resp.json()["data"]["items"]


async def generate(
    llm: httpx.AsyncClient, model: str, system: str, question: str
) -> tuple[str, float]:
    started = time.perf_counter()
    resp = await llm.post(
        "/chat/completions",
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": question},
            ],
            "temperature": 0.0,
            "max_tokens": 500,
        },
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip(), time.perf_counter() - started


def measure(answer: str, evidence: list[dict]) -> dict:
    violations = audit_answer(answer, evidence)
    return {
        "chars": len(answer),
        "violations": len(violations),
        "violation_kinds": [v.kind for v in violations],
        "citation_coverage": round(citation_coverage(answer), 3),
        "refused": bool(REFUSAL_RE.search(answer)) and not re.search(r"\[\d+\]", answer),
        "has_ref_line": "参考：" in answer,
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter-model", default="campus-lora")
    parser.add_argument("--base-model", default="qwen2.5-7b-instruct")
    parser.add_argument("--qa", default=str(REPO_ROOT / "eval" / "qa.json"))
    parser.add_argument("--out", default="/hy-tmp/campus/data/sft/eval")
    parser.add_argument("--api-base", default="http://127.0.0.1:8080")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    settings = get_settings()
    qa = json.loads(Path(args.qa).read_text(encoding="utf-8"))
    if args.limit:
        qa = qa[: args.limit]

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(base_url=settings.llm_base_url.rstrip("/"), timeout=120) as llm, httpx.AsyncClient(
        timeout=60
    ) as client:
        token = await admin_token(client, args.api_base)
        results = []
        for idx, item in enumerate(qa, 1):
            question = item["question"]
            chunks = await retrieve(client, args.api_base, token, question)
            evidence = [
                {
                    "filename": c.get("filename"),
                    "page_no": c.get("page_no"),
                    "content": c.get("content", ""),
                }
                for c in chunks
            ]
            system = SYSTEM_PROMPT.format(
                version=PROMPT_VERSION,
                role_tone=ROLE_TONE["student"],
                evidence=format_evidence(evidence),
                evidence_count=len(evidence),
            )
            base_answer, base_s = await generate(llm, args.base_model, system, question)
            adapter_answer, adapter_s = await generate(llm, args.adapter_model, system, question)
            results.append(
                {
                    "id": item["id"],
                    "question": question,
                    "gold_doc": item.get("gold_doc", ""),
                    "evidence_files": [c.get("filename") for c in chunks],
                    "base": {"answer": base_answer, "seconds": round(base_s, 2), **measure(base_answer, evidence)},
                    "adapter": {"answer": adapter_answer, "seconds": round(adapter_s, 2), **measure(adapter_answer, evidence)},
                }
            )
            print(f"[{idx}/{len(qa)}] {item['id']} 完成", flush=True)

    def summary(key: str) -> dict:
        rows = [r[key] for r in results]
        answerable = [r[key] for r, q in zip(results, qa) if q.get("gold_doc")]
        outside = [r[key] for r, q in zip(results, qa) if not q.get("gold_doc")]
        return {
            "avg_chars": round(sum(x["chars"] for x in rows) / len(rows), 1),
            "avg_seconds": round(sum(x["seconds"] for x in rows) / len(rows), 2),
            "violations_total": sum(x["violations"] for x in rows),
            "answers_with_violation": sum(1 for x in rows if x["violations"]),
            "avg_citation_coverage": round(sum(x["citation_coverage"] for x in rows) / len(rows), 3),
            "ref_line_rate": round(sum(1 for x in rows if x["has_ref_line"]) / len(rows), 3),
            "refusal_rate_outside": round(sum(1 for x in outside if x["refused"]) / max(1, len(outside)), 3),
            "refusal_rate_answerable": round(sum(1 for x in answerable if x["refused"]) / max(1, len(answerable)), 3),
        }

    report = {"count": len(results), "base": summary("base"), "adapter": summary("adapter")}
    (out_dir / "compare.json").write_text(
        json.dumps({"report": report, "results": results}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
