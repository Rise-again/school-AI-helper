"""登录、刷新、当前用户。"""

from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.core.errors import AuthRequired, Forbidden
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.repositories.users import UserRepository


class AuthService:
    def __init__(self, settings: Settings, users: UserRepository) -> None:
        self._settings = settings
        self._users = users

    def _issue(self, user: dict[str, Any]) -> dict[str, Any]:
        user_id = int(user["id"])
        role = str(user["role"])
        return {
            "access_token": create_access_token(self._settings, user_id=user_id, role=role),
            "refresh_token": create_refresh_token(self._settings, user_id=user_id, role=role),
            "token_type": "bearer",
            "expires_in": self._settings.jwt_expire_minutes * 60,
        }

    async def login(self, username: str, password: str) -> dict[str, Any]:
        user = await self._users.get_by_username(username)
        # 统一话术，避免暴露"用户是否存在"
        if user is None:
            raise AuthRequired("用户名或密码不正确")

        if user["status"] != "active":
            raise Forbidden("账号已停用，请联系管理员")

        locked, remain = UserRepository.is_locked(user)
        if locked:
            raise Forbidden(f"账号已锁定，请 {remain} 分钟后重试")

        if not verify_password(password, user["password_hash"]):
            row = await self._users.register_failure(int(user["id"]))
            locked_now, remain_now = UserRepository.is_locked(row)
            if locked_now:
                raise Forbidden(f"连续输错次数过多，账号锁定 {remain_now} 分钟")
            raise AuthRequired("用户名或密码不正确")

        await self._users.reset_failure(int(user["id"]))
        return self._issue(user)

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        payload = decode_token(self._settings, refresh_token, expect="refresh")
        user_id = int(payload["sub"])
        user = await self._users.get_by_id(user_id)
        if user is None or user["status"] != "active":
            raise AuthRequired("账号不可用，请重新登录")
        return self._issue(user)

    async def current_user(self, user_id: int, role: str) -> dict[str, Any]:
        user = await self._users.get_by_id(user_id)
        if user is None or user["status"] != "active":
            raise AuthRequired("账号不可用，请重新登录")
        profile = await self._users.get_profile(user_id) if role == "student" else None
        return {
            "id": int(user["id"]),
            "username": user["username"],
            "role": user["role"],
            "student_no": (profile or {}).get("student_no"),
            "name": (profile or {}).get("name"),
        }
