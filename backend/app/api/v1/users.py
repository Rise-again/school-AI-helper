"""当前用户信息。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, envelope, get_auth_service, get_current_user
from app.schemas.common import UserOut
from app.services.auth_service import AuthService

router = APIRouter(tags=["user"])


@router.get("/me", summary="当前用户与角色")
async def me(
    user: CurrentUser = Depends(get_current_user),
    svc: AuthService = Depends(get_auth_service),
) -> dict:
    data = await svc.current_user(user.id, user.role)
    return envelope(0, "ok", UserOut(**data).model_dump())
