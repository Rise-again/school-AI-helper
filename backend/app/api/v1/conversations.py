"""会话增删改查与消息列表。

发消息（SSE）在 P3 实现，这里只提供已落库消息的读取。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query

from app.api.deps import CurrentUser, envelope, get_conversation_service, require_roles
from app.schemas.common import (
    ConversationCreate,
    ConversationOut,
    ConversationRename,
    MessageOut,
)
from app.services.conversation_service import ConversationService

router = APIRouter(prefix="/conversations", tags=["conversations"])

_student_or_admin = require_roles("student", "admin")


@router.get("", summary="会话列表（分页，按更新时间倒序）")
async def list_conversations(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    user: CurrentUser = Depends(_student_or_admin),
    svc: ConversationService = Depends(get_conversation_service),
) -> dict:
    data = await svc.list(user_id=user.id, page=page, size=size)
    data["items"] = [ConversationOut(**item).model_dump() for item in data["items"]]
    return envelope(0, "ok", data)


@router.post("", summary="新建会话")
async def create_conversation(
    payload: ConversationCreate,
    user: CurrentUser = Depends(_student_or_admin),
    svc: ConversationService = Depends(get_conversation_service),
) -> dict:
    conv = await svc.create(user_id=user.id, role_mode=user.role, title=payload.title)
    return envelope(0, "创建成功", ConversationOut(**conv).model_dump())


@router.get("/{conversation_id}", summary="会话详情")
async def get_conversation(
    conversation_id: int = Path(ge=1),
    user: CurrentUser = Depends(_student_or_admin),
    svc: ConversationService = Depends(get_conversation_service),
) -> dict:
    conv = await svc.get(user_id=user.id, conversation_id=conversation_id)
    return envelope(0, "ok", ConversationOut(**conv).model_dump())


@router.patch("/{conversation_id}", summary="重命名")
async def rename_conversation(
    payload: ConversationRename,
    conversation_id: int = Path(ge=1),
    user: CurrentUser = Depends(_student_or_admin),
    svc: ConversationService = Depends(get_conversation_service),
) -> dict:
    conv = await svc.rename(user_id=user.id, conversation_id=conversation_id, title=payload.title)
    return envelope(0, "已重命名", ConversationOut(**conv).model_dump())


@router.delete("/{conversation_id}", summary="删除会话（软删除，级联消息）")
async def delete_conversation(
    conversation_id: int = Path(ge=1),
    user: CurrentUser = Depends(_student_or_admin),
    svc: ConversationService = Depends(get_conversation_service),
) -> dict:
    await svc.delete(user_id=user.id, conversation_id=conversation_id)
    return envelope(0, "已删除", None)


@router.get("/{conversation_id}/messages", summary="消息列表（按时间正序）")
async def list_messages(
    conversation_id: int = Path(ge=1),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    user: CurrentUser = Depends(_student_or_admin),
    svc: ConversationService = Depends(get_conversation_service),
) -> dict:
    data = await svc.messages(
        user_id=user.id, conversation_id=conversation_id, page=page, size=size
    )
    data["items"] = [MessageOut(**item).model_dump() for item in data["items"]]
    return envelope(0, "ok", data)
