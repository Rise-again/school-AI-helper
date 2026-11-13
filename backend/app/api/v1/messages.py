"""流式对话接口（SSE）。

事件序列：meta → delta* → citation → done
异常：error（此时消息可能未落库，前端提示重试）
心跳：`: ping` 注释行，每 2.5 秒一次，防止代理 4 秒空闲超时断流。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, get_chat_service, require_roles
from app.services.chat_service import ChatService

router = APIRouter(prefix="/conversations", tags=["chat"])
guest_router = APIRouter(tags=["chat"])
_student_or_admin = require_roles("student", "admin")


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class GuestAsk(BaseModel):
    content: str = Field(min_length=1, max_length=500)


@router.post("/{conversation_id}/messages", summary="发消息，SSE 流式返回")
async def send_message(
    payload: MessageCreate,
    conversation_id: int = Path(ge=1),
    user: CurrentUser = Depends(_student_or_admin),
    svc: ChatService = Depends(get_chat_service),
) -> StreamingResponse:
    # 归属校验放在建流之前，否则 404 只能以 error 事件形式返回
    await svc.ensure_owned(user_id=user.id, conversation_id=conversation_id)

    async def event_stream():
        try:
            async for event, data in svc.stream_reply(
                user_id=user.id,
                role=user.role,
                conversation_id=conversation_id,
                content=payload.content,
            ):
                if event == "ping":
                    yield ": ping\n\n"
                else:
                    yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001 - 流已开始，只能以事件告知
            body = {"message": f"服务异常：{exc.__class__.__name__}"}
            yield f"event: error\ndata: {json.dumps(body, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@guest_router.post("/chat/anonymous", summary="访客匿名提问（不落库，按 IP 限流）")
async def ask_anonymous(
    payload: GuestAsk,
    request: Request,
    svc: ChatService = Depends(get_chat_service),
) -> StreamingResponse:
    """访客通道：不写会话表，刷新即失；限流按客户端 IP。"""
    client_key = request.client.host if request.client else "unknown"
    svc.ensure_guest_allowed(client_key)  # 先判限流，保证超限返回 429 而不是 error 事件

    async def event_stream():
        try:
            async for event, data in svc.stream_guest(query=payload.content.strip(), client_key=client_key):
                if event == "ping":
                    yield ": ping\n\n"
                else:
                    yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001
            body = {"message": f"服务异常：{exc.__class__.__name__}"}
            yield f"event: error\ndata: {json.dumps(body, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
