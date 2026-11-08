"""知识库管理接口（仅管理员）。"""

from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, Depends, File, Form, Path, Query, UploadFile

from app.api.deps import CurrentUser, envelope, get_kb_service, require_roles
from app.core.errors import ValidationFailed
from app.schemas.common import KbChunkOut, KbFileOut
from app.services.kb_service import KbService

router = APIRouter(prefix="/kb", tags=["knowledge-base"])
_admin = require_roles("admin")


def _parse_date(raw: str | None, field: str) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValidationFailed(f"{field} 需为 YYYY-MM-DD 格式") from exc


def _file_payload(row: dict) -> dict:
    return KbFileOut(**row).model_dump(mode="json")


def _chunk_payload(row: dict) -> dict:
    meta = row.get("meta_json")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except ValueError:
            meta = {}
    return KbChunkOut(
        id=row["id"],
        ordinal=row["ordinal"],
        content=row["content"],
        token_count=row["token_count"],
        vector_id=row["vector_id"],
        meta=meta or {},
        created_at=row["created_at"],
    ).model_dump(mode="json")


@router.post("/files", summary="上传文档（异步解析入库）")
async def upload_file(
    file: UploadFile = File(...),
    source_dept: str | None = Form(default=None),
    source_url: str | None = Form(default=None),
    effective_from: str | None = Form(default=None),
    effective_to: str | None = Form(default=None),
    admin: CurrentUser = Depends(_admin),
    svc: KbService = Depends(get_kb_service),
) -> dict:
    if not file.filename:
        raise ValidationFailed("缺少文件名")
    content = await file.read()
    record = await svc.upload(
        filename=file.filename,
        content=content,
        uploaded_by=admin.id,
        source_dept=source_dept,
        source_url=source_url,
        effective_from=_parse_date(effective_from, "effective_from"),
        effective_to=_parse_date(effective_to, "effective_to"),
    )
    return envelope(0, "已受理，正在解析", _file_payload(record))


@router.get("/files", summary="入库文件列表")
async def list_files(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    status: str | None = Query(default=None, pattern="^(pending|parsing|success|failed)$"),
    _admin: CurrentUser = Depends(_admin),
    svc: KbService = Depends(get_kb_service),
) -> dict:
    data = await svc.list_files(page=page, size=size, status=status)
    data["items"] = [_file_payload(item) for item in data["items"]]
    return envelope(0, "ok", data)


@router.get("/files/{file_id}", summary="文件详情")
async def get_file(
    file_id: int = Path(ge=1),
    _admin: CurrentUser = Depends(_admin),
    svc: KbService = Depends(get_kb_service),
) -> dict:
    return envelope(0, "ok", _file_payload(await svc.get_file(file_id)))


@router.get("/files/{file_id}/chunks", summary="切片明细")
async def list_chunks(
    file_id: int = Path(ge=1),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _admin: CurrentUser = Depends(_admin),
    svc: KbService = Depends(get_kb_service),
) -> dict:
    data = await svc.list_chunks(file_id=file_id, page=page, size=size)
    data["items"] = [_chunk_payload(item) for item in data["items"]]
    return envelope(0, "ok", data)


@router.post("/files/{file_id}/reindex", summary="重建索引")
async def reindex(
    file_id: int = Path(ge=1),
    _admin: CurrentUser = Depends(_admin),
    svc: KbService = Depends(get_kb_service),
) -> dict:
    return envelope(0, "已开始重建", _file_payload(await svc.reindex(file_id)))


@router.delete("/files/{file_id}", summary="删除文件与向量")
async def delete_file(
    file_id: int = Path(ge=1),
    _admin: CurrentUser = Depends(_admin),
    svc: KbService = Depends(get_kb_service),
) -> dict:
    await svc.delete(file_id)
    return envelope(0, "已删除", None)
