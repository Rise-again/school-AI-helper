"""登录 / 刷新 / 注销。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import envelope, get_auth_service
from app.schemas.common import LoginRequest, RefreshRequest, TokenPair
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", summary="登录，返回 access + refresh 令牌")
async def login(payload: LoginRequest, svc: AuthService = Depends(get_auth_service)) -> dict:
    tokens = await svc.login(payload.username, payload.password)
    return envelope(0, "登录成功", TokenPair(**tokens).model_dump())


@router.post("/refresh", summary="用 refresh 令牌换新的一对令牌")
async def refresh(payload: RefreshRequest, svc: AuthService = Depends(get_auth_service)) -> dict:
    tokens = await svc.refresh(payload.refresh_token)
    return envelope(0, "刷新成功", TokenPair(**tokens).model_dump())


@router.post("/logout", summary="注销（无状态，客户端丢弃令牌即可）")
async def logout() -> dict:
    # 当前不维护令牌黑名单：access 过期即失效。
    # 若后续需要"立即失效"，可在 MySQL 建 revoked_jti 表并在此写入。
    return envelope(0, "已退出登录", None)
