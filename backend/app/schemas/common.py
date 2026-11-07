"""请求/响应模型。请求一律校验；响应保持与 OpenAPI 一致。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=72)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=10)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    student_no: str | None = None
    name: str | None = None


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=128)


class ConversationRename(BaseModel):
    title: str = Field(min_length=1, max_length=128)


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    role_mode: str
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    tokens: int | None = None
    latency_ms: int | None = None
    created_at: datetime


class PageMeta(BaseModel):
    total: int
    page: int
    size: int
