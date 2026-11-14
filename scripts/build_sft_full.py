"""P4-01 正式 SFT 数据构造（在服务器上跑，依赖 vLLM 与 MySQL）。

流程：
1. 从 kb_chunk 取制度类文档切片，清洗 OCR 换行/页眉；
2. 让基座模型按切片生成 3 个学生口吻问题；
3. 用线上同一套系统提示词生成回答，落地校验（grounding.audit_answer）不通过就丢；
4. 同一问题再生成访客/管理员两种语气；每个问题再改写一个口语变体；
5. 拒答样本用"无关证据 + 库外问题"生成并校验；
6. 与评测集做 3-gram 相似度去重，按 9:1 切训练/验证，输出 LLaMA-Factory sharegpt JSON。

用法（服务器）：
    /hy-tmp/campus/venvs/web/bin/python scripts/build_sft_full.py --chunks 60
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import aiomysql  # noqa: E402
import httpx  # noqa: E402

from app.agents.state import ROLE_TONE, SYSTEM_PROMPT, format_evidence  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.services.grounding import audit_answer  # noqa: E402
from build_sft_samples import build_records as build_preview  # noqa: E402

PROMPT_VERSION = "p4-sft-v1"
POLICY_FILES = (4, 6, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21)
CONCURRENCY = 5
MAX_ANSWER_CHARS = 330

QUESTION_PROMPT = """你是学校政策答疑助手。下面是《{filename}》里的一段原文（OCR 可能有断行，已整理）。
请站在学生角度提出 {n} 个口语化、彼此不同的问题。要求：
1. 每个问题都必须能仅凭这段原文回答；
2. 不要出现原文没有的岗位名、数字、材料名、部门名；
3. 每行一个问题，不要编号、不要引号、不要解释。

原文：
{content}
"""

REWRITE_PROMPT = """把下面这个问题换一种更口语的说法，只输出一句问题，不要解释：
{question}
"""

REFUSAL_TEMPLATES = [
    "资料中没有直接说明这一点。现有资料与这个问题无关，不能作为回答依据。建议直接咨询学校相关部门，或查看官网最新通知。",
    "我没有在知识库里找到与这个问题直接相关的依据，为避免给出错误信息，这里不做推测。建议关注学校官网通知或咨询辅导员。",
    "资料中没有直接说明这一点，这里不做推测。建议以学校官方最新通知为准，或直接咨询相关部门。",
]

REFUSAL_QUESTIONS = [
    "新生军训什么时候开始？要准备什么？",
    "宿舍是几人间？有空调和独立卫生间吗？",
    "学校食堂一个月生活费大概多少？",
    "从三亚凤凰机场到学校怎么走？有接站吗？",
    "校园卡丢了去哪里补办？",
    "学校有几个校区？新生在哪个校区？",
    "图书馆周末开放到几点？",
    "学校附近有快递点吗？",
    "新生入学需要迁户口吗？",
    "学校有校医院吗？医保怎么办理？",
    "学生社团什么时候招新？",
    "操场晚上开放到几点？",
    "学校给新生统一办银行卡吗？",
    "宿舍可以自己装洗衣机吗？",
    "辅导员办公室在哪栋楼？",
    "学校有没有游泳馆？收费吗？",
    "国庆节放假怎么安排？",
    "补考一般安排在什么时候？",
    "教室空调坏了找谁修？",
    "学校有没有通宵自习室？",
]

DROP_LINE = (
    re.compile(r"^-+\s*\d+\s*-+$"),
    re.compile(r"^第[一二三四五六七八九十]+篇"),
    re.compile(r"^学生手册"),
    re.compile(r"^\d+$"),
)


def clean_text(raw: str) -> str:
    lines = []
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        if any(p.match(s) for p in DROP_LINE):
            continue
        lines.append(s)
    text = "".join(lines)
    text = re.sub(r"\s+", "", text)
    text = text.replace("海南热带海洋学院海南热带海洋学院", "海南热带海洋学院")
    return text.strip()


def norm(text: str) -> str:
    return re.sub(r"[\s，。；：、！？,.!?;:\"'“”‘’（）()《》]", "", text or "")


def ngrams(text: str, n: int = 3) -> set[str]:
    t = norm(text)
    return {t[i : i + n] for i in range(max(0, len(t) - n + 1))}


def jaccard(a: str, b: str) -> float:
    ga, gb = ngrams(a), ngrams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def citation_coverage(answer: str) -> float:
    body = re.sub(r"参考：.*", "", answer)
    sentences = [s for s in re.split(r"(?<=[。；！？\n])", body) if len(re.findall(r"[一-龥]", s)) >= 6]
    if not sentences:
        return 1.0
    return sum(1 for s in sentences if re.search(r"\[\d+\]", s)) / len(sentences)


def answer_ok(answer: str, evidence: list[dict]) -> str | None:
    if not answer or len(answer) > MAX_ANSWER_CHARS:
        return "length"
    if "参考：" not in answer:
        return "no_ref_line"
    if not re.search(r"\[\d+\]", answer):
        return "no_citation"
    if citation_coverage(answer) < 0.8:
        return "weak_citation"
    if audit_answer(answer, evidence):
        return "audit"
    return None


class Builder:
    def __init__(self, settings) -> None:
        self.settings = settings
        self.http = httpx.AsyncClient(
            base_url=settings.llm_base_url.rstrip("/"),
            timeout=httpx.Timeout(120.0),
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
        )
        self.sem = asyncio.Semaphore(CONCURRENCY)
        self.stats = {"questions": 0, "answers_ok": 0, "drop": {}, "roles": {}, "refusal": 0}

    async def chat(self, messages: list[dict], *, temperature: float = 0.3, max_tokens: int = 500) -> str:
        async with self.sem:
            resp = await self.http.post(
                "/chat/completions",
                json={
                    "model": self.settings.llm_model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()

    async def make_answer(self, question: str, evidence: list[dict], role: str) -> str | None:
        system = SYSTEM_PROMPT.format(
            version=PROMPT_VERSION,
            role_tone=ROLE_TONE[role],
            evidence=format_evidence(evidence),
            evidence_count=len(evidence),
        )
        answer = await self.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": question}],
            temperature=0.2,
            max_tokens=420,
        )
        if len(answer) > MAX_ANSWER_CHARS:
            # 超长先压缩一次，保留编号与参考行；压不下来再丢
            answer = await self.chat(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": question},
                    {"role": "assistant", "content": answer},
                    {"role": "user", "content": "请把上面的回答压缩到 300 字以内：只保留直接回答问题的内容，保留所有 [编号] 和最后一行“参考：”，只输出压缩后的回答。"},
                ],
                temperature=0.1,
                max_tokens=420,
            )
        if citation_coverage(answer) < 0.8:
            # 标注不全就让它补编号，不改内容；仍不达标则丢弃
            answer = await self.chat(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": question},
                    {"role": "assistant", "content": answer},
                    {"role": "user", "content": "上面的回答里有的句子缺少编号。请只给每一条事实句末尾补上 [1]，不要增删或改写任何内容，保持最后一行“参考：”不变，只输出补好编号的回答。"},
                ],
                temperature=0.1,
                max_tokens=420,
            )
        reason = answer_ok(answer, evidence)
        if reason:
            self.stats["drop"][reason] = self.stats["drop"].get(reason, 0) + 1
            return None
        return answer

    async def questions_for(self, chunk: dict, n: int = 5) -> list[str]:
        raw = await self.chat(
            [{"role": "user", "content": QUESTION_PROMPT.format(filename=chunk["filename"], n=n, content=chunk["content"][:700])}],
            temperature=0.7,
            max_tokens=320,
        )
        questions = []
        for line in raw.splitlines():
            q = re.sub(r"^[\d\.\-、\s]+", "", line).strip().strip('"“”')
            if 6 <= len(q) <= 60 and ("？" in q or "?" in q):
                questions.append(q.rstrip("?") + "？")
        return questions[:n]

    async def rewrite(self, question: str) -> str | None:
        try:
            q = await self.chat(
                [{"role": "user", "content": REWRITE_PROMPT.format(question=question)}],
                temperature=0.8,
                max_tokens=80,
            )
        except Exception:
            return None
        q = q.strip().strip('"“”')
        if 6 <= len(q) <= 60 and ("？" in q or "?" in q) and jaccard(q, question) < 0.75:
            return q.rstrip("?") + "？"
        return None

    async def build_chunk(self, chunk: dict) -> list[dict]:
        out: list[dict] = []
        evidence = [
            {
                "filename": chunk["filename"],
                "page_no": chunk["page_no"],
                "content": chunk["content"],
            }
        ]
        questions = await self.questions_for(chunk)
        self.stats["questions"] += len(questions)
        for q in questions:
            personal = any(mark in q for mark in ("我", "本人", "咱"))
            variants = [(q, "student")]
            alt = await self.rewrite(q)
            if alt:
                variants.append((alt, "student"))
            if not personal:
                # 个人化问题只保留学生口吻：访客/管理员不该回答"我能拿多少"
                for role in ("guest", "admin"):
                    variants.append((q, role))
            for question, role in variants:
                answer = await self.make_answer(question, evidence, role)
                if not answer:
                    continue
                self.stats["answers_ok"] += 1
                self.stats["roles"][role] = self.stats["roles"].get(role, 0) + 1
                out.append(
                    {
                        "system": SYSTEM_PROMPT.format(
                            version=PROMPT_VERSION,
                            role_tone=ROLE_TONE[role],
                            evidence=format_evidence(evidence),
                            evidence_count=len(evidence),
                        ),
                        "conversations": [
                            {"from": "human", "value": question},
                            {"from": "gpt", "value": answer},
                        ],
                        "_meta": {"kind": "policy", "role": role, "file": chunk["filename"]},
                    }
                )
        return out

    async def build_refusals(self, distractor_pool: list[dict]) -> list[dict]:
        out = []
        for idx, question in enumerate(REFUSAL_QUESTIONS):
            chunk = distractor_pool[idx % len(distractor_pool)]
            evidence = [{"filename": chunk["filename"], "page_no": chunk["page_no"], "content": chunk["content"][:600]}]
            system = SYSTEM_PROMPT.format(
                version=PROMPT_VERSION,
                role_tone=ROLE_TONE["student"],
                evidence=format_evidence(evidence),
                evidence_count=1,
            )
            # 拒答用固定模板：基座模型在无关证据下仍会硬答并挂编号，
            # 这正是要教它避免的行为，所以不采用模型生成结果。
            answer = REFUSAL_TEMPLATES[idx % len(REFUSAL_TEMPLATES)]
            self.stats["refusal"] += 1
            out.append(
                {
                    "system": system,
                    "conversations": [
                        {"from": "human", "value": question},
                        {"from": "gpt", "value": answer},
                    ],
                    "_meta": {"kind": "refusal", "role": "student", "file": chunk["filename"]},
                }
            )
        return out


async def load_chunks(settings, limit: int, offset: int = 0) -> list[dict]:
    conn = await aiomysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        db=settings.mysql_db,
        charset="utf8mb4",
    )
    sql = (
        "SELECT c.id, c.content, c.token_count, c.meta_json, f.filename "
        "FROM kb_chunk c JOIN kb_file f ON f.id = c.kb_file_id "
        "WHERE c.kb_file_id IN (" + ",".join(["%s"] * len(POLICY_FILES)) + ") "
        "AND c.token_count >= 80 AND c.content NOT LIKE '%%|%%'"
    )
    async with conn.cursor(aiomysql.DictCursor) as cur:
        await cur.execute(sql, POLICY_FILES)
        rows = await cur.fetchall()
    conn.close()
    random.seed(42)
    random.shuffle(rows)
    rows = rows[offset:]
    chunks = []
    for row in rows:
        text = clean_text(row["content"])
        if len(text) < 150 or len(re.findall(r"[一-龥]", text)) < 60:
            continue
        meta = row["meta_json"] or {}
        if isinstance(meta, str):
            meta = json.loads(meta)
        chunks.append(
            {
                "id": row["id"],
                "filename": row["filename"],
                "page_no": meta.get("page_no") or 1,
                "content": text[:900],
            }
        )
        if len(chunks) >= limit:
            break
    return chunks


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunks", type=int, default=60)
    parser.add_argument("--offset", type=int, default=0, help="跳过前 N 个切片（分批生成时用）")
    parser.add_argument("--out-dir", default="/hy-tmp/campus/data/sft")
    args = parser.parse_args()

    settings = get_settings()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    chunks = await load_chunks(settings, args.chunks, args.offset)
    print(f"选中切片 {len(chunks)} 条", flush=True)

    builder = Builder(settings)
    records: list[dict] = []
    for idx, chunk in enumerate(chunks, 1):
        try:
            items = await builder.build_chunk(chunk)
        except Exception as exc:  # noqa: BLE001
            print(f"chunk {chunk['id']} 失败：{type(exc).__name__}: {exc}", flush=True)
            continue
        records.extend(items)
        if idx % 10 == 0:
            print(f"进度 {idx}/{len(chunks)}，累计 {len(records)} 条", flush=True)

    # 拒答：用与问题无关的制度片段当干扰证据
    records.extend(await builder.build_refusals(chunks))

    # 高质量人工样例（16 条，含多轮/冲突/寒暄）
    preview = build_preview()
    for rec in preview:
        rec = dict(rec)
        rec["_meta"] = {"kind": "seed", "role": "mixed", "file": "samples_preview"}
        records.append(rec)

    # 去重：与评测集、训练集内部
    eval_path = REPO_ROOT / "eval" / "qa.json"
    eval_questions = []
    if eval_path.is_file():
        eval_questions = [item["question"] for item in json.loads(eval_path.read_text(encoding="utf-8"))]

    kept: list[dict] = []
    seen: list[tuple[str, str]] = []
    dropped = {"eval_overlap": 0, "internal_dup": 0}
    for rec in records:
        question = rec["conversations"][0]["value"]
        role = str(rec.get("_meta", {}).get("role", "?"))
        if any(jaccard(question, q) > 0.55 for q in eval_questions):
            dropped["eval_overlap"] += 1
            continue
        # 同一问题的不同角色语气是有效样本，去重按 (问题, 角色) 而不是只看问题
        if any(jaccard(question, q) > 0.85 and role == r for q, r in seen):
            dropped["internal_dup"] += 1
            continue
        seen.append((question, role))
        kept.append(rec)

    random.seed(42)
    random.shuffle(kept)
    split = int(len(kept) * 0.9)
    train, val = kept[:split], kept[split:]

    def dump(path: Path, rows: list[dict]) -> None:
        # 只保留训练需要的两列，避免 _meta/id 之类字段进数据集
        clean_rows = [
            {"system": rec.get("system", ""), "conversations": rec["conversations"]}
            for rec in rows
        ]
        path.write_text(json.dumps(clean_rows, ensure_ascii=False, indent=1), encoding="utf-8")

    dump(out_dir / "train.json", train)
    dump(out_dir / "val.json", val)

    kinds: dict[str, int] = {}
    roles: dict[str, int] = {}
    lengths = []
    for rec in kept:
        meta = rec.get("_meta", {})
        kinds[meta.get("kind", "?")] = kinds.get(meta.get("kind", "?"), 0) + 1
        roles[meta.get("role", "?")] = roles.get(meta.get("role", "?"), 0) + 1
        lengths.append(len(rec["conversations"][-1]["value"]))

    report = {
        "chunks": len(chunks),
        "total": len(kept),
        "train": len(train),
        "val": len(val),
        "kinds": kinds,
        "roles": roles,
        "refusals": builder.stats["refusal"],
        "drop": {**builder.stats["drop"], **dropped},
        "answer_chars": {
            "min": min(lengths) if lengths else 0,
            "max": max(lengths) if lengths else 0,
            "avg": sum(lengths) // len(lengths) if lengths else 0,
        },
    }
    (out_dir / "build_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    await builder.http.aclose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
