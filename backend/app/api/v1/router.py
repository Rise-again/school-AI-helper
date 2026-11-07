"""v1 路由汇总。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import auth, conversations, users

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(conversations.router)
