"""口令与令牌的单元测试。"""

from __future__ import annotations

import time

import jwt
import pytest

from app.core.config import Settings
from app.core.errors import AuthRequired, TokenExpired
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from tests.conftest import BASE_ENV


@pytest.fixture()
def settings() -> Settings:
    return Settings.from_env(env_file=None, environ=BASE_ENV)


def test_password_hash_roundtrip():
    hashed = hash_password("Passw0rd!")
    assert hashed.startswith("$2")
    assert verify_password("Passw0rd!", hashed)
    assert not verify_password("Passw0rd", hashed)


def test_password_too_long_rejected():
    with pytest.raises(ValueError):
        hash_password("密" * 30)  # UTF-8 90 字节 > 72


def test_verify_tolerates_broken_hash():
    assert verify_password("anything", "not-a-bcrypt-hash") is False


def test_access_token_roundtrip(settings: Settings):
    token = create_access_token(settings, user_id=7, role="student")
    payload = decode_token(settings, token, expect="access")
    assert payload["sub"] == "7"
    assert payload["role"] == "student"


def test_refresh_token_cannot_be_used_as_access(settings: Settings):
    token = create_refresh_token(settings, user_id=7, role="student")
    with pytest.raises(AuthRequired):
        decode_token(settings, token, expect="access")


def test_expired_token(settings: Settings):
    now = int(time.time())
    token = jwt.encode(
        {"sub": "1", "role": "student", "typ": "access", "iat": now - 100, "exp": now - 10},
        settings.jwt_secret,
        algorithm="HS256",
    )
    with pytest.raises(TokenExpired):
        decode_token(settings, token, expect="access")


def test_tampered_token_rejected(settings: Settings):
    token = create_access_token(settings, user_id=1, role="student")
    with pytest.raises(AuthRequired):
        decode_token(settings, token[:-2] + "xx", expect="access")


def test_token_signed_by_other_secret_rejected(settings: Settings):
    other = Settings.from_env(
        env_file=None, environ={**BASE_ENV, "JWT_SECRET": "ffffffffffffffffffffffffffffffff"}
    )
    token = create_access_token(other, user_id=1, role="admin")
    with pytest.raises(AuthRequired):
        decode_token(settings, token, expect="access")
