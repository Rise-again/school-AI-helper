"""标题感知的 token 切片。

规则（来自计划 3.2 第 2 条）：
- 每片估算 token ≤ CHUNK_MAX_TOKENS（默认 480，bge 上限 512 留余量）
- 目标 CHUNK_TARGET_TOKENS（默认 400），相邻片重叠 CHUNK_OVERLAP_TOKENS（默认 80）
- heading_path 取该片**最后一个**标题，即最具体的章节路径
- page_no 取该片**起始**块的页码，引用时指到"从第几页开始"
- 代码块、表格整块保留，超长才按句子/字符拆
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.rag.tokens import estimate_tokens, hard_split, tail_by_tokens

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    content: str
    tokens: int
    heading_path: str
    page_no: int | None


@dataclass
class _Block:
    text: str
    heading_path: str
    page_no: int | None
    tokens: int
    is_heading: bool = False


def _make_block(
    text: str, heading_path: str, page_no: int | None, *, is_heading: bool = False
) -> _Block:
    return _Block(
        text=text,
        heading_path=heading_path,
        page_no=page_no,
        tokens=estimate_tokens(text),
        is_heading=is_heading,
    )


def _blocks_from_page(text: str, page_no: int | None, stack: list[str]) -> list[_Block]:
    blocks: list[_Block] = []
    buf: list[str] = []
    in_fence = False

    def flush() -> None:
        if not buf:
            return
        joined = "\n".join(buf).strip()
        buf.clear()
        if joined:
            blocks.append(_make_block(joined, " > ".join(stack), page_no))

    for raw in text.split("\n"):
        line = raw.rstrip()
        if line.strip().startswith("```"):
            buf.append(line)
            in_fence = not in_fence
            if not in_fence:
                flush()
            continue
        if in_fence:
            buf.append(line)
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            flush()
            level = len(heading.group(1))
            title = heading.group(2).strip()
            if level <= len(stack):
                del stack[level - 1 :]
            stack.append(title)
            blocks.append(_make_block(title, " > ".join(stack), page_no, is_heading=True))
            continue

        if not line.strip():
            flush()
            continue

        buf.append(line)

    flush()
    return blocks


def _split_oversized(block: _Block, max_tokens: int) -> list[_Block]:
    if block.tokens <= max_tokens:
        return [block]
    return [_make_block(piece, block.heading_path, block.page_no) for piece in hard_split(block.text, max_tokens)]


def chunk_pages(
    pages: list[tuple[int | None, str]],
    *,
    target_tokens: int = 400,
    max_tokens: int = 480,
    overlap_tokens: int = 80,
) -> list[Chunk]:
    if target_tokens > max_tokens:
        raise ValueError("target_tokens 不能大于 max_tokens")
    if overlap_tokens >= target_tokens:
        raise ValueError("overlap_tokens 必须小于 target_tokens")

    stack: list[str] = []
    blocks: list[_Block] = []
    for page_no, text in pages:
        for block in _blocks_from_page(text, page_no, stack):
            blocks.extend(_split_oversized(block, max_tokens))

    chunks: list[Chunk] = []
    current: list[_Block] = []
    current_tokens = 0

    def emit(content: str, heading_path: str, page_no: int | None) -> None:
        pieces = hard_split(content, max_tokens) if estimate_tokens(content) > max_tokens else [content]
        for piece in pieces:
            piece = piece.strip()
            if piece:
                chunks.append(
                    Chunk(
                        ordinal=len(chunks),
                        content=piece,
                        tokens=estimate_tokens(piece),
                        heading_path=heading_path,
                        page_no=page_no,
                    )
                )

    def flush(keep_overlap: bool = True) -> None:
        nonlocal current, current_tokens
        if not current:
            return
        content = "\n\n".join(b.text for b in current).strip()
        if not content:
            current, current_tokens = [], 0
            return
        # 最具体的标题 + 起始页码
        emit(content, current[-1].heading_path, current[0].page_no)
        if not keep_overlap:
            current, current_tokens = [], 0
            return
        tail = tail_by_tokens(content, overlap_tokens)
        current = [_make_block(tail, current[-1].heading_path, current[0].page_no)] if tail else []
        current_tokens = estimate_tokens(tail) if tail else 0

    for block in blocks:
        # 标题是天然的语义边界：已经有正文时遇到新标题就直接切，且不带重叠
        # （跨章节的重叠会把上一章的内容混进新章节，反而拉低重排分数）
        if block.is_heading and any(not b.is_heading for b in current):
            flush(keep_overlap=False)
        elif current and current_tokens + block.tokens > target_tokens:
            flush()
        current.append(block)
        current_tokens += block.tokens

    if current:
        content = "\n\n".join(b.text for b in current).strip()
        if content:
            emit(content, current[-1].heading_path, current[0].page_no)

    return chunks
