"""token 估算与句子切分。

为什么不用模型分词器：bge 的 tokenizer 在云端，本地切片刻意不引入 transformers。
这里的估算**宁可高估**——高估只会让切片偏小（安全），低估会导致超 512 被静默截断（危险）。
真实 token 数在云端可用 bge tokenizer 复核，见 docs/07-测试计划.md。
"""

from __future__ import annotations

import math
import re

_CJK_RANGES = (
    (0x3400, 0x4DBF),  # 扩展 A
    (0x4E00, 0x9FFF),  # 基本区
    (0xF900, 0xFAFF),  # 兼容
    (0x3000, 0x303F),  # 中文标点
    (0xFF00, 0xFFEF),  # 全角
)
_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-]*")
_SENT_BREAK = re.compile(r"(?<=[。！？；!?;])|(?<=[.]\s)")


def is_cjk(ch: str) -> bool:
    code = ord(ch)
    return any(low <= code <= high for low, high in _CJK_RANGES)


def estimate_tokens(text: str) -> int:
    """保守估算：CJK 记 1，英文词按 1.3，其余符号按 0.5，另加 2 的边界开销。"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if is_cjk(ch))
    words = _WORD_RE.findall(text)
    word_len = sum(len(w) for w in words)
    others = max(len(text) - cjk - word_len, 0)
    return cjk + math.ceil(len(words) * 1.3) + math.ceil(others * 0.5) + 2


def split_sentences(text: str) -> list[str]:
    """按中英文句末标点切分，保留标点。"""
    parts = [p for p in _SENT_BREAK.split(text) if p and p.strip()]
    return parts or ([text] if text else [])


def tail_by_tokens(text: str, tokens: int) -> str:
    """从尾部截取约 tokens 个 token 的文本，尽量落在句子边界。"""
    if tokens <= 0 or not text:
        return ""
    sentences = split_sentences(text)
    picked: list[str] = []
    used = 0
    for sentence in reversed(sentences):
        cost = estimate_tokens(sentence)
        if used + cost > tokens and picked:
            break
        picked.append(sentence)
        used += cost
        if used >= tokens:
            break
    if not picked:  # 单句就超了，退化为按字符截断
        return text[-tokens:]
    return "".join(reversed(picked)).strip()


def hard_split(text: str, max_tokens: int) -> list[str]:
    """把超长文本切成若干段，保证每段**实测估算**不超上限（含边界开销）。"""
    budget = max(1, max_tokens - 2)  # estimate_tokens 末尾 +2，这里预留
    if estimate_tokens(text) <= max_tokens:
        return [text]
    pieces: list[str] = []
    buf = ""
    for sentence in split_sentences(text):
        if estimate_tokens(buf + sentence) <= budget:
            buf += sentence
            continue
        if buf:
            pieces.append(buf)
        # 单句仍然超限：按字符切，切完复核
        while estimate_tokens(sentence) > budget:
            cut = max(1, int(len(sentence) * budget / max(estimate_tokens(sentence), 1)))
            pieces.append(sentence[:cut])
            sentence = sentence[cut:]
        buf = sentence
    if buf:
        pieces.append(buf)
    return [p for p in pieces if p.strip()]
