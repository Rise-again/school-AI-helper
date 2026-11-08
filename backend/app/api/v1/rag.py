"""检索调试接口（仅管理员）。

上线后前台问答走 Agent（P3），这里保留一个可直接看召回结果的入口，
用于调阈值、排索引问题、给评测集跑分。
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Query

from app.api.deps import envelope, get_retriever, require_roles
from app.rag.retriever import Retriever

router = APIRouter(prefix="/rag", tags=["rag"])
_admin = require_roles("admin")


@router.get("/search", summary="按问题检索知识库（含分数与引用信息）")
async def search(
    q: str = Query(min_length=1, max_length=200),
    top_n: int | None = Query(default=None, ge=1, le=20),
    include_expired: bool = Query(default=False),
    _admin=Depends(_admin),
    retriever: Retriever = Depends(get_retriever),
) -> dict:
    chunks = await retriever.search(q, top_n=top_n, include_expired=include_expired)
    items = [asdict(chunk) for chunk in chunks]
    return envelope(0, "ok", {"query": q, "count": len(items), "items": items})
