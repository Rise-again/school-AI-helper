"""回答落地校验：把"资料里没有的具体内容"抓出来。

7B 模型在资料没写时会用常识补全——补出岗位名、材料清单、金额。
提示词只能降低概率，不能消灭。这里再加一道**确定性**闸门：
回答里出现的书名号标题、带单位的数字、以及"包括/如/例如"后面列举的名词，
必须在参考资料原文里找得到，否则判为无依据。

判为无依据后有两种处置：先让模型按违规清单重写一次；仍不合规则直接删掉涉事句子。
任何情况下都不允许把凭空捏造的具体信息送到用户面前。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 归一化：去掉空白与标点，避免"20 小时"和"20小时"这种差异造成误判
_STRIP = str.maketrans("", "", " \t\r\n　（）()《》「」『』“”\"'、，。；：！？,.;:!?·…—-")
# 口语虚词不影响"是不是同一个说法"
_SOFT = str.maketrans("", "", "的了等")

_TITLE_RE = re.compile(r"《([^》]{2,40})》")
_NUM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(个工作日|元|小时|天数|天|人|次|分|月|周|%|％)")
_ENUM_RE = re.compile(
    r"(?:包括(?:但不限于)?|例如|比如|如|含|提供|提交|准备|携带|出具)([^。；！？\n]{2,80})"
)
_ENUM_LEAD = ("但不限于", "诸如", "以下", "这些", "各类", "各项")
_ENUM_TAIL_RE = re.compile(r"等[^，。；、]{0,3}$")


@dataclass(frozen=True)
class Violation:
    kind: str  # title / number / item
    span: str  # 回答里那句话中找不到出处的片段
    sentence: str  # 所在句子，用于精确删除


def _norm(text: str) -> str:
    return text.translate(_STRIP)


def _core(text: str) -> str:
    return _norm(text).translate(_SOFT)


def _appears(item: str, evidence_core: str) -> bool:
    """片段是否在资料里出现。

    除了整段子串匹配，还允许"被页眉页脚打断"的情况：
    PDF 里的表格名常被页码切成两半（"海南热带海洋 -167- 海南热带海洋学院 …申请表"），
    这时按二元组覆盖率判断，八成以上能对上就算有依据。
    """
    core = _core(item)
    if len(core) < 2:
        return True
    if core in evidence_core:
        return True
    if len(core) >= 4:
        grams = {core[i : i + 2] for i in range(len(core) - 1)}
        hits = sum(1 for g in grams if g in evidence_core)
        return hits / len(grams) >= 0.8
    return False


def split_sentences(text: str) -> list[str]:
    """按句末标点切句，保留标点；换行也视作句子边界。"""
    parts = re.split(r"(?<=[。；！？\n])", text)
    return [p for p in parts if p.strip()]


def audit_answer(answer: str, evidence: list[dict]) -> list[Violation]:
    """返回回答里找不到资料依据的具体片段。空列表表示通过。"""
    if not answer or not evidence:
        return []
    joined = "\n".join(str(e.get("content") or "") for e in evidence)
    evidence_core = _core(joined)
    evidence_norm = _norm(joined)

    violations: list[Violation] = []
    for sentence in split_sentences(answer):
        if "参考：" in sentence:
            continue
        # 去掉 [1] 这类标注再抽取，否则"等材料 [1]"会把编号带进列举项
        clean = re.sub(r"\[\d+\]", "", sentence)
        for marker in re.findall(r"\[(\d+)\]", sentence):
            if int(marker) > len(evidence):
                violations.append(Violation("citation", f"[{marker}]", sentence))
        for title in _TITLE_RE.findall(clean):
            if not _appears(title, evidence_core):
                violations.append(Violation("title", title, sentence))

        for num, unit in _NUM_RE.findall(clean):
            if f"{num}{unit}" not in evidence_norm:
                violations.append(Violation("number", f"{num}{unit}", sentence))

        for captured in _ENUM_RE.findall(clean):
            # 只认顿号分隔的真列举；逗号分隔的常常是一句连贯的话，容易误判
            items = [x for x in captured.split("、") if x.strip()]
            if len(items) < 2:
                continue
            for raw in items:
                item = raw.strip()
                for lead in _ENUM_LEAD:
                    if item.startswith(lead):
                        item = item[len(lead) :]
                item = _ENUM_TAIL_RE.sub("", item).rstrip("等")
                if not 2 <= len(item) <= 12 or not re.search(r"[一-龥]", item):
                    continue
                if not _appears(item, evidence_core):
                    violations.append(Violation("item", item, sentence))
    # 去重（同一片段只报一次）
    seen: set[tuple[str, str]] = set()
    unique: list[Violation] = []
    for v in violations:
        key = (v.kind, v.span)
        if key not in seen:
            seen.add(key)
            unique.append(v)
    return unique


def drop_violations(answer: str, violations: list[Violation]) -> str:
    """确定性兜底：删掉含无依据片段的整句；越界编号只摘掉编号，不删句子。

    句子内容本身没问题、只是编号写错时（模型写了 [7] 而资料只有 3 条），
    整句删掉太浪费，摘掉编号即可。
    """
    bad_sentences = {v.sentence for v in violations if v.kind != "citation"}
    kept = [s for s in split_sentences(answer) if s not in bad_sentences]
    text = "".join(kept)
    for v in violations:
        if v.kind == "citation":
            text = text.replace(v.span, "")
    return text.strip()


def violation_brief(violations: list[Violation]) -> str:
    """给模型看的违规清单。"""
    return "、".join(dict.fromkeys(v.span for v in violations))
