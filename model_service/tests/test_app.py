"""模型服务契约测试：用假后端，不依赖 GPU 与真实权重。"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import create_app


class FakeBackend:
    dim = 8

    def __init__(self) -> None:
        self.ocr_calls: list[tuple[str, list[int] | None]] = []

    def embed(self, texts):
        return [[1.0 / math.sqrt(self.dim)] * self.dim for _ in texts]

    def rerank(self, query, passages):
        # 越长越相关，便于断言排序
        return [min(1.0, len(p) / 10) for p in passages]

    def ocr(self, path: Path, pages):
        self.ocr_calls.append((path.suffix, pages))
        targets = pages or [1, 2]
        return {p: f"第{p}页识别文本" for p in targets}

    def status(self):
        return {"embedding": "loaded", "rerank": "loaded", "ocr": "loaded"}


@pytest.fixture()
def backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture()
def client(backend):
    with TestClient(create_app(backend, api_key="")) as c:
        yield c


def test_healthz_reports_models(client):
    body = client.get("/healthz").json()
    assert body["status"] == "ok"
    assert body["dim"] == 8
    assert set(body["models"]) == {"embedding", "rerank", "ocr"}


def test_embeddings_shape(client):
    resp = client.post("/v1/embeddings", json={"input": ["学籍管理", "考试纪律"]})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert [d["index"] for d in data] == [0, 1]
    assert all(len(d["embedding"]) == 8 for d in data)


def test_embeddings_rejects_empty(client):
    assert client.post("/v1/embeddings", json={"input": [""]}).status_code == 400
    assert client.post("/v1/embeddings", json={"input": []}).status_code == 422


def test_rerank_orders_and_truncates(client):
    passages = ["短", "中等长度的段落", "这是一段比较长的候选文本内容"]
    resp = client.post("/v1/rerank", json={"query": "考试", "passages": passages, "top_k": 2})
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results) == 2
    assert results[0]["index"] == 2
    assert results[0]["relevance_score"] >= results[1]["relevance_score"]


def test_rerank_can_return_documents(client):
    resp = client.post(
        "/v1/rerank", json={"query": "q", "passages": ["a"], "return_documents": True}
    )
    assert resp.json()["results"][0]["document"]["text"] == "a"


def test_ocr_pages_are_sorted(client, backend):
    resp = client.post(
        "/v1/ocr", files={"file": ("scan.pdf", b"%PDF-fake", "application/pdf")}, data={"pages": "2,1"}
    )
    assert resp.status_code == 200
    pages = resp.json()["pages"]
    assert [p["page_no"] for p in pages] == [1, 2]
    assert backend.ocr_calls == [(".pdf", [2, 1])]


def test_ocr_rejects_bad_pages(client):
    resp = client.post(
        "/v1/ocr", files={"file": ("a.png", b"x", "image/png")}, data={"pages": "1,x"}
    )
    assert resp.status_code == 400


def test_api_key_enforced(backend):
    with TestClient(create_app(backend, api_key="s3cret")) as c:
        assert c.post("/v1/embeddings", json={"input": ["a"]}).status_code == 401
        ok = c.post(
            "/v1/embeddings", json={"input": ["a"]}, headers={"Authorization": "Bearer s3cret"}
        )
        assert ok.status_code == 200
        ok2 = c.post("/v1/embeddings", json={"input": ["a"]}, headers={"X-API-Key": "s3cret"})
        assert ok2.status_code == 200
