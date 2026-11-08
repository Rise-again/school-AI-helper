"""接口层公共依赖：取配置、取连接池、鉴权、角色校验。"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings
from app.core.errors import AuthRequired, Forbidden
from app.core.logging import trace_id_var
from app.core.security import decode_token
from app.db.pool import Database
from app.services.auth_service import AuthService
from app.services.conversation_service import ConversationService
from app.rag.retriever import Retriever
from app.services.kb_service import KbService

_bearer = HTTPBearer(auto_error=False)


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_auth_service(request: Request) -> AuthService:
    return request.app.state.auth_service


def get_conversation_service(request: Request) -> ConversationService:
    return request.app.state.conversation_service


def get_kb_service(request: Request) -> KbService:
    return request.app.state.kb_service


def get_retriever(request: Request) -> Retriever:
    return request.app.state.retriever


@dataclass(frozen=True)
class CurrentUser:
    id: int
    role: str


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    if credentials is None or not credentials.credentials:
        raise AuthRequired("请先登录")
    payload = decode_token(settings, credentials.credentials, expect="access")
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthRequired("登录凭证无效") from exc
    return CurrentUser(id=user_id, role=str(payload.get("role", "")))


def require_roles(*allowed: str):
    """用法：Depends(require_roles("admin"))"""

    async def _checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed:
            raise Forbidden()
        return user

    return _checker


def envelope(code: int = 0, message: str = "ok", data=None) -> dict:
    return {"code": code, "message": message, "data": data, "trace_id": trace_id_var.get()}
