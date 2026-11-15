"""P8-01：向量库封装的分支测试。"""

from __future__ import annotations

import pytest

from app.core.errors import DependencyUnavailable
from app.rag.store import InMemoryVectorStore, UnavailableVectorStore, _sanitize_metadata


def test_inmemory_upsert_query_delete():
    store = InMemoryVectorStore()
    store.upsert(
        ids=["c1", "c2"],
        documents=["农业", "工业"],
        embeddings=[[1.0, 0.0], [0.0, 1.0]],
        metadatas=[{"kb_file_id": 1, "page_no": 1, "ok": True, "bad": object()}, {"kb_file_id": 2}],
    )
    assert store.count() == 2
    hits = store.query(embedding=[1.0, 0.0], top_k=2)
    assert hits[0]["id"] == "c1"
    assert hits[0]["score"] == pytest.approx(1.0)
    assert "bad" not in hits[0]["metadata"]

    assert len(store.query(embedding=[1.0, 0.0], top_k=2, where={"kb_file_id": 2})) == 1
    store.delete_by_file(1)
    assert store.count() == 1
    assert store.query(embedding=[1.0, 0.0], top_k=1)[0]["id"] == "c2"


def test_unavailable_store_raises_clearly():
    store = UnavailableVectorStore("磁盘损坏")
    with pytest.raises(DependencyUnavailable) as exc:
        store.query(embedding=[0.0], top_k=1)
    assert "磁盘损坏" in str(exc.value)
    with pytest.raises(DependencyUnavailable):
        store.count()
    with pytest.raises(DependencyUnavailable):
        store.upsert(ids=[], documents=[], embeddings=[], metadatas=[])
    with pytest.raises(DependencyUnavailable):
        store.delete_by_file(1)


def test_sanitize_metadata_keeps_only_chroma_types():
    assert _sanitize_metadata({"a": 1, "b": 1.2, "c": True, "d": "x", "e": [1]}) == {
        "a": 1,
        "b": 1.2,
        "c": True,
        "d": "x",
    }
