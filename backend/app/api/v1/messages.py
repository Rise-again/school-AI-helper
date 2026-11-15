"""流式对话接口（SSE）。

事件序列：meta → delta* → [replace] → citation → done
replace：落地校验命中（回答里有资料中没有的具体内容）时，服务端重写或删句，
         前端用其中的 text 整段替换已显示的内容。
异常：error（此时消息可能未落库，前端提示重试）
心跳：`: ping` 注释行，每 2.5 秒一次，防止代理 4 秒空闲超时断流。
"""

from __future__ import annotations

import json
import logging
import secrets

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, get_chat_gate, get_chat_service, require_roles
from app.core.rate_limit import QueueGate
from app.services.chat_service import ChatService

router = APIRouter(prefix="/conversations", tags=["chat"])
guest_router = APIRouter(tags=["chat"])
_student_or_admin = require_roles("student", "admin")
logger = logging.getLogger("campus.chat")


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class GuestAsk(BaseModel):
    content: str = Field(min_length=1, max_length=500)


@router.post("/{conversation_id}/messages", summary="发消息，SSE 流式返回")
async def send_message(
    payload: MessageCreate,
    request: Request,
    conversation_id: int = Path(ge=1),
    user: CurrentUser = Depends(_student_or_admin),
    svc: ChatService = Depends(get_chat_service),
    gate: QueueGate = Depends(get_chat_gate),
) -> StreamingResponse:
    # 归属校验放在建流之前，否则 404 只能以 error 事件形式返回
    await svc.ensure_owned(user_id=user.id, conversation_id=conversation_id)
    # 双维度限流与排队都在建流前完成：超限返回真正的 429，而不是 error 事件
    client_ip = request.client.host if request.client else "unknown"
    svc.ensure_allowed(user_id=user.id, client_key="", ip=client_ip)
    ticket = await gate.acquire(identity=f"user:{user.id}")

    async def event_stream():
        try:
            async for event, data in svc.stream_reply(
                user_id=user.id,
                role=user.role,
                conversation_id=conversation_id,
                content=payload.content,
                queued_ms=ticket.waited_ms,
            ):
                if event == "ping":
                    yield ": ping\n\n"
                else:
                    yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001 - 流已开始，只能以事件告知
            logger.exception("stream_failed", extra={"extra_fields": {"path": "messages"}})
            body = {"message": "服务暂时不可用，请稍后再试"}
            yield f"event: error\ndata: {json.dumps(body, ensure_ascii=False)}\n\n"
        finally:
            ticket.release()

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
    gate: QueueGate = Depends(get_chat_gate),
) -> StreamingResponse:
    """访客通道：不写会话表，刷新即失；按浏览器访客 cookie 限流。

    平台代理会把来源 IP 折叠成网关地址，且 X-Forwarded-For 可伪造，
    所以首次访问下发 `visitor_id` cookie，后续以它作为访客额度主键。
    """
    existing = request.cookies.get("visitor_id")
    visitor_id = existing or secrets.token_hex(8)
    client_ip = request.client.host if request.client else "unknown"
    # 先判限流与排队，保证超限返回 429 而不是流里的 error 事件
    svc.ensure_allowed(user_id=None, client_key=visitor_id, ip=client_ip)
    ticket = await gate.acquire(identity=f"guest:{visitor_id}")

    async def event_stream():
        try:
            async for event, data in svc.stream_guest(
                query=payload.content.strip(), client_key=visitor_id, queued_ms=ticket.waited_ms
            ):
                if event == "ping":
                    yield ": ping\n\n"
                else:
                    yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001
            logger.exception("stream_failed", extra={"extra_fields": {"path": "anonymous"}})
            body = {"message": "服务暂时不可用，请稍后再试"}
            yield f"event: error\ndata: {json.dumps(body, ensure_ascii=False)}\n\n"
        finally:
            ticket.release()

    response = StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
    if existing is None:
        # 30 天有效；httponly 防止前端脚本误改，访客额度以它为主键
        response.set_cookie(
            "visitor_id",
            visitor_id,
            max_age=30 * 24 * 3600,
            httponly=True,
            samesite="lax",
        )
    return response
