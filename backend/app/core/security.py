"""口令哈希与 JWT。

- 口令用 bcrypt（自带 salt，成本因子默认 12）。
- JWT 用 HS256，access / refresh 用 typ 区分，刷新时不换密钥。
- 所有失败都抛 AuthRequired 子类，由全局处理器转成 2001/2002。
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Literal

import bcrypt
import jwt

from app.core.config import Settings
from app.core.errors import AuthRequired, TokenExpired

_BCRYPT_MAX_BYTES = 72  # bcrypt 硬限制，超长会被静默截断
TokenType = Literal["access", "refresh"]


def hash_password(password: str) -> str:
    raw = password.encode("utf-8")
    if len(raw) > _BCRYPT_MAX_BYTES:
        raise ValueError("口令过长（UTF-8 超过 72 字节）")
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    raw = password.encode("utf-8")
    if len(raw) > _BCRYPT_MAX_BYTES:
        return False
    try:
        return bcrypt.checkpw(raw, password_hash.encode("utf-8"))
    except ValueError:
        # 库里存了非 bcrypt 格式（例如迁移数据出错），视为验证失败而不是 500
        return False


def _encode(settings: Settings, *, user_id: int, role: str, typ: TokenType, ttl_seconds: int) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "typ": typ,
        "iat": now,
        "nbf": now,
        "exp": now + ttl_seconds,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_alg)


def create_access_token(settings: Settings, *, user_id: int, role: str) -> str:
    return _encode(
        settings, user_id=user_id, role=role, typ="access",
        ttl_seconds=settings.jwt_expire_minutes * 60,
    )


def create_refresh_token(settings: Settings, *, user_id: int, role: str) -> str:
    return _encode(
        settings, user_id=user_id, role=role, typ="refresh",
        ttl_seconds=settings.jwt_refresh_expire_days * 86400,
    )


def decode_token(settings: Settings, token: str, *, expect: TokenType) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_alg],
            options={"require": ["exp", "sub", "typ"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpired() from exc
    except jwt.InvalidTokenError as exc:
        raise AuthRequired("登录凭证无效") from exc

    if payload.get("typ") != expect:
        raise AuthRequired("登录凭证类型不匹配")
    return payload
