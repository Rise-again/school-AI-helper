"""向量库封装。

生产用 ChromaDB（PersistentClient，单进程写入，见计划 3.2 第 1 条）；
测试用内存实现，避免为了跑单测去装几百 MB 的依赖。

约定：向量由外部算好再写入（collection 不挂 embedding_function），
      metadata 只放 Chroma 支持的类型（str/int/float/bool）。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Protocol, Sequence

logger = logging.getLogger("campus.vectorstore")


class VectorStore(Protocol):
    def upsert(
        self,
        *,
        ids: Sequence[str],
        documents: Sequence[str],
        embeddings: Sequence[Sequence[float]],
        metadatas: Sequence[dict[str, Any]],
    ) -> None: ...

    def delete_by_file(self, kb_file_id: int) -> None: ...

    def count(self) -> int: ...


def _sanitize_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in meta.items() if isinstance(v, (str, int, float, bool))}


class ChromaVectorStore:
    def __init__(self, persist_dir: Path | str, collection: str = "campus_kb") -> None:
        import chromadb  # 延迟导入：未装 chromadb 时不影响其它功能

        Path(persist_dir).mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(persist_dir))
        self._collection = self._client.get_or_create_collection(
            name=collection,
            metadata={"hnsw:space": "cosine"},
            embedding_function=None,
        )
        logger.info("chroma_ready", extra={"collection": collection, "count": self._collection.count()})

    def upsert(self, *, ids, documents, embeddings, metadatas) -> None:
        self._collection.upsert(
            ids=list(ids),
            documents=list(documents),
            embeddings=[list(map(float, vec)) for vec in embeddings],
            metadatas=[_sanitize_metadata(m) for m in metadatas],
        )

    def delete_by_file(self, kb_file_id: int) -> None:
        self._collection.delete(where={"kb_file_id": int(kb_file_id)})

    def count(self) -> int:
        return int(self._collection.count())


class InMemoryVectorStore:
    """测试替身：行为与 Chroma 一致（按 kb_file_id 可删、可计数）。"""

    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}

    def upsert(self, *, ids, documents, embeddings, metadatas) -> None:
        for idx, _ in enumerate(ids):
            self.items[ids[idx]] = {
                "document": documents[idx],
                "embedding": list(embeddings[idx]),
                "metadata": _sanitize_metadata(metadatas[idx]),
            }

    def delete_by_file(self, kb_file_id: int) -> None:
        doomed = [
            key
            for key, item in self.items.items()
            if int(item["metadata"].get("kb_file_id", -1)) == int(kb_file_id)
        ]
        for key in doomed:
            self.items.pop(key, None)

    def count(self) -> int:
        return len(self.items)


class UnavailableVectorStore:
    """chromadb 未安装或初始化失败时的占位：用的时候明确报错，而不是静默返回空结果。"""

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def _raise(self) -> None:
        from app.core.errors import DependencyUnavailable

        raise DependencyUnavailable(f"向量库不可用：{self.reason}")

    def upsert(self, **kwargs) -> None:  # noqa: ANN003
        self._raise()

    def delete_by_file(self, kb_file_id: int) -> None:
        self._raise()

    def count(self) -> int:
        self._raise()
        return 0
