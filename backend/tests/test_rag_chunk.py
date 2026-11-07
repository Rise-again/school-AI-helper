"""切片器的行为测试：宁可切小也不能超限。"""

from __future__ import annotations

from app.rag.chunker import chunk_pages
from app.rag.tokens import estimate_tokens


def _long_text(paragraphs: int = 40) -> str:
    return "\n\n".join(
        f"第{i}条 学生应当按照学校规定完成课程学习，考试合格后方可获得相应学分。"
        f"如有作弊行为，按学校相关规定处理，情节严重的取消学位授予资格。"
        for i in range(paragraphs)
    )


def test_small_doc_produces_single_chunk():
    chunks = chunk_pages([(None, "图书馆开放时间为每日 8:00 至 22:00。")])
    assert len(chunks) == 1
    assert chunks[0].ordinal == 0
    assert "图书馆" in chunks[0].content


def test_every_chunk_within_token_limit():
    chunks = chunk_pages([(None, _long_text())], target_tokens=400, max_tokens=480, overlap_tokens=80)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.tokens <= 480, chunk.tokens
        assert estimate_tokens(chunk.content) <= 480


def test_ordinals_are_sequential():
    chunks = chunk_pages([(None, _long_text(10))])
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))


def test_heading_path_is_captured():
    text = "# 第一章 总则\n\n## 第一节 学籍\n\n学生入学后三个月内进行资格复查。"
    chunks = chunk_pages([(None, text)])
    assert chunks[0].heading_path == "第一章 总则 > 第一节 学籍"


def test_adjacent_chunks_overlap():
    chunks = chunk_pages([(None, _long_text(12))], target_tokens=200, max_tokens=240, overlap_tokens=60)
    assert len(chunks) >= 2
    # 尾片与下一片头片应有重叠内容
    first_tail = chunks[0].content[-40:]
    assert first_tail in chunks[1].content or chunks[1].content[:40] in chunks[0].content


def test_unpunctuated_blob_is_hard_split():
    blob = "学" * 4000
    chunks = chunk_pages([(None, blob)], target_tokens=400, max_tokens=480, overlap_tokens=80)
    assert len(chunks) >= 8
    for chunk in chunks:
        assert chunk.tokens <= 480


def test_table_rows_are_kept_together():
    table = "\n".join(["| 项目 | 标准 |", "|---|---|"] + [f"| 学费{i} | {5000 + i} 元 |" for i in range(5)])
    chunks = chunk_pages([(None, "收费标准如下：\n\n" + table)])
    assert "| 学费0 | 5000 元 |" in chunks[0].content


def test_page_numbers_propagate():
    chunks = chunk_pages([(1, "第一页内容，关于学籍管理。"), (2, "第二页内容，关于考试纪律。")])
    assert chunks[0].page_no == 1
    assert any(c.page_no == 2 for c in chunks) or len(chunks) == 1


def test_empty_input():
    assert chunk_pages([]) == []
    assert chunk_pages([(None, "   ")]) == []
