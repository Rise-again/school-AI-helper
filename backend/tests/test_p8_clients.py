"""P8-01：HTTP 客户端分支测试（不依赖真实模型服务）。

用 httpx.MockTransport 注入假响应，覆盖成功、HTTP 错误、格式错误、流式结束等分支。
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.core.errors import DependencyUnavailable, ModelUnavailable
from app.integrations.anysearch import AnySearchClient
from app.integrations.llm_client import LLMClient
from app.rag.embedding import EXPECTED_DIM, HttpEmbeddingClient
from app.rag.ocr import HttpOcrClient
from app.rag.rerank import HttpRerankerClient


def mock_client(client, handler) -> None:
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ---------- LLM ----------
def test_llm_chat_success():
    client = LLMClient("http://llm/v1", "m")
    mock_client(
        client,
        lambda request: httpx.Response(200, json={"choices": [{"message": {"content": " 你好 "}}]}),
    )
    assert asyncio.run(client.chat([{"role": "user", "content": "hi"}])) == "你好"


def test_llm_chat_http_error():
    client = LLMClient("http://llm/v1", "m")
    mock_client(client, lambda request: httpx.Response(500))
    with pytest.raises(ModelUnavailable):
        asyncio.run(client.chat([{"role": "user", "content": "hi"}]))


def test_llm_chat_bad_json():
    client = LLMClient("http://llm/v1", "m")
    mock_client(client, lambda request: httpx.Response(200, text="not-json", headers={"content-type": "application/json"}))
    with pytest.raises(ModelUnavailable):
        asyncio.run(client.chat([{"role": "user", "content": "hi"}]))


def test_llm_chat_bad_shape():
    client = LLMClient("http://llm/v1", "m")
    mock_client(client, lambda request: httpx.Response(200, json={"choices": []}))
    with pytest.raises(ModelUnavailable):
        asyncio.run(client.chat([{"role": "user", "content": "hi"}]))


def test_llm_stream_success_and_done():
    body = (
        'data: {"choices":[{"delta":{"content":"你"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"好"}}]}\n\n'
        "data: [DONE]\n\n"
    )
    client = LLMClient("http://llm/v1", "m")
    mock_client(client, lambda request: httpx.Response(200, text=body))

    async def collect():
        return [chunk async for chunk in client.stream([{"role": "user", "content": "hi"}])]

    assert asyncio.run(collect()) == ["你", "好"]


def test_llm_stream_http_error():
    client = LLMClient("http://llm/v1", "m")
    mock_client(client, lambda request: httpx.Response(500))

    async def collect():
        return [chunk async for chunk in client.stream([{"role": "user", "content": "hi"}])]

    with pytest.raises(ModelUnavailable):
        asyncio.run(collect())


# ---------- Embedding ----------
def test_embedding_success_and_aclose():
    vec = [0.01] * EXPECTED_DIM
    client = HttpEmbeddingClient("http://models")
    mock_client(
        client,
        lambda request: httpx.Response(200, json={"data": [{"index": 0, "embedding": vec}]}),
    )
    out = asyncio.run(client.embed(["你好"]))
    assert len(out) == 1 and len(out[0]) == EXPECTED_DIM
    asyncio.run(client.aclose())


def test_embedding_dimension_mismatch():
    client = HttpEmbeddingClient("http://models")
    mock_client(
        client,
        lambda request: httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1]}]}),
    )
    with pytest.raises(DependencyUnavailable):
        asyncio.run(client.embed(["你好"]))


def test_embedding_count_mismatch():
    client = HttpEmbeddingClient("http://models")
    mock_client(client, lambda request: httpx.Response(200, json={"data": []}))
    with pytest.raises(DependencyUnavailable):
        asyncio.run(client.embed(["a", "b"]))


def test_embedding_http_error():
    client = HttpEmbeddingClient("http://models")
    mock_client(client, lambda request: httpx.Response(503))
    with pytest.raises(DependencyUnavailable):
        asyncio.run(client.embed(["你好"]))


# ---------- Rerank ----------
def test_rerank_success():
    client = HttpRerankerClient("http://models")
    mock_client(
        client,
        lambda request: httpx.Response(
            200, json={"results": [{"index": 1, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.2}]}
        ),
    )
    assert asyncio.run(client.rerank("q", ["a", "b"])) == [0.2, 0.9]


def test_rerank_empty_and_error():
    client = HttpRerankerClient("http://models")
    assert asyncio.run(client.rerank("q", [])) == []
    mock_client(client, lambda request: httpx.Response(500))
    with pytest.raises(DependencyUnavailable):
        asyncio.run(client.rerank("q", ["a"]))


# ---------- OCR ----------
def test_ocr_success(tmp_path):
    client = HttpOcrClient("http://models")
    mock_client(
        client,
        lambda request: httpx.Response(
            200, json={"pages": [{"page_no": 1, "text": "第一页"}, {"page_no": 2, "text": "第二页"}]}
        ),
    )
    path = tmp_path / "a.pdf"
    path.write_bytes(b"%PDF-1.4")
    assert asyncio.run(client.ocr_file(path)) == {1: "第一页", 2: "第二页"}


def test_ocr_error_and_text_fallback(tmp_path):
    client = HttpOcrClient("http://models")
    mock_client(client, lambda request: httpx.Response(200, json={"text": "整体文本"}))
    path = tmp_path / "b.pdf"
    path.write_bytes(b"x")
    assert asyncio.run(client.ocr_file(path)) == {0: "整体文本"}

    mock_client(client, lambda request: httpx.Response(500))
    with pytest.raises(DependencyUnavailable):
        asyncio.run(client.ocr_file(path))


# ---------- AnySearch ----------
def test_anysearch_disabled_returns_empty():
    client = AnySearchClient("http://search", "")
    assert client.enabled is False
    assert asyncio.run(client.search("q")) == []


def test_anysearch_filters_domain_and_prefers_article():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "results": [
                            {"title": "首页", "url": "https://www.hntou.edu.cn/", "content": "导航"},
                            {
                                "title": "通知",
                                "url": "https://www.hntou.edu.cn/t20260101_1.html",
                                "content": "正文摘要",
                            },
                            {"title": "外站", "url": "https://example.com/a", "content": "外站"},
                        ]
                    }
                },
            )
        return httpx.Response(
            200,
            text="<html><body><article>" + "正文内容。" * 40 + "</article></body></html>",
        )

    client = AnySearchClient("http://search", "key", fetch_body=True, fetch_max=2)
    mock_client(client, handler)
    items = asyncio.run(client.search("通知"))
    assert [it["url"] for it in items] == ["https://www.hntou.edu.cn/t20260101_1.html"]
    assert "正文内容" in items[0]["content"]


def test_anysearch_http_error_and_helpers():
    client = AnySearchClient("http://search", "key")
    mock_client(client, lambda request: httpx.Response(500))
    with pytest.raises(DependencyUnavailable):
        asyncio.run(client.search("q"))

    assert client.build_query("放假通知") == "放假通知 hntou.edu.cn"
    assert client.cache_key("q") == client.cache_key(" q ")
    assert "q" in client.dumps([{"q": "值"}])
    assert client._looks_like_article("https://x/t20260101_1.html") is True
    assert client._looks_like_article("https://x/") is False
    assert "正文" in client.extract_text("<html><body><p>正文。</p></body></html>")
