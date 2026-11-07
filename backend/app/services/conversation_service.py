"""会话的增删改查。

越权一律返回 404（而不是 403）：不暴露"这个 id 存在但不属于你"。
"""

from __future__ import annotations

from typing import Any

from app.core.errors import NotFound
from app.repositories.conversations import ConversationRepository


class ConversationService:
    def __init__(self, conversations: ConversationRepository) -> None:
        self._repo = conversations

    async def create(self, *, user_id: int, role_mode: str, title: str | None) -> dict[str, Any]:
        conv_id = await self._repo.create(user_id=user_id, role_mode=role_mode, title=title or "新会话")
        conv = await self._repo.get(user_id=user_id, conversation_id=conv_id)
        if conv is None:  # 理论上不会发生
            raise NotFound("会话创建失败")
        return conv

    async def list(self, *, user_id: int, page: int, size: int) -> dict[str, Any]:
        items, total = await self._repo.list_by_user(user_id=user_id, page=page, size=size)
        return {"items": items, "total": total, "page": page, "size": size}

    async def get(self, *, user_id: int, conversation_id: int) -> dict[str, Any]:
        conv = await self._repo.get(user_id=user_id, conversation_id=conversation_id)
        if conv is None:
            raise NotFound("会话不存在")
        return conv

    async def rename(self, *, user_id: int, conversation_id: int, title: str) -> dict[str, Any]:
        ok = await self._repo.rename(user_id=user_id, conversation_id=conversation_id, title=title)
        if not ok:
            raise NotFound("会话不存在")
        return await self.get(user_id=user_id, conversation_id=conversation_id)

    async def delete(self, *, user_id: int, conversation_id: int) -> None:
        ok = await self._repo.soft_delete(user_id=user_id, conversation_id=conversation_id)
        if not ok:
            raise NotFound("会话不存在")

    async def messages(self, *, user_id: int, conversation_id: int, page: int, size: int) -> dict[str, Any]:
        await self.get(user_id=user_id, conversation_id=conversation_id)  # 校验归属
        items, total = await self._repo.list_messages(conversation_id=conversation_id, page=page, size=size)
        return {"items": items, "total": total, "page": page, "size": size}
