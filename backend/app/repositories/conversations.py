"""会话与消息的数据访问。"""

from __future__ import annotations

from typing import Any

from app.db.pool import Database


class ConversationRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    # ---------- 会话 ----------
    async def create(self, *, user_id: int, role_mode: str, title: str = "新会话") -> int:
        async with self._db.cursor() as cur:
            await cur.execute(
                "INSERT INTO conversation (user_id, role_mode, title) VALUES (%s, %s, %s)",
                (user_id, role_mode, title),
            )
            return int(cur.lastrowid)

    async def get(self, *, user_id: int, conversation_id: int) -> dict[str, Any] | None:
        sql = (
            "SELECT id, user_id, title, role_mode, created_at, updated_at "
            "FROM conversation WHERE id = %s AND user_id = %s AND deleted_at IS NULL"
        )
        async with self._db.cursor() as cur:
            await cur.execute(sql, (conversation_id, user_id))
            return await cur.fetchone()

    async def list_by_user(self, *, user_id: int, page: int, size: int) -> tuple[list[dict[str, Any]], int]:
        offset = (page - 1) * size
        async with self._db.cursor() as cur:
            await cur.execute(
                "SELECT COUNT(*) AS c FROM conversation WHERE user_id = %s AND deleted_at IS NULL",
                (user_id,),
            )
            total = int((await cur.fetchone())["c"])
            await cur.execute(
                "SELECT id, title, role_mode, created_at, updated_at "
                "FROM conversation WHERE user_id = %s AND deleted_at IS NULL "
                "ORDER BY updated_at DESC, id DESC LIMIT %s OFFSET %s",
                (user_id, size, offset),
            )
            rows = await cur.fetchall()
        return list(rows), total

    async def rename(self, *, user_id: int, conversation_id: int, title: str) -> bool:
        async with self._db.cursor() as cur:
            await cur.execute(
                "UPDATE conversation SET title = %s "
                "WHERE id = %s AND user_id = %s AND deleted_at IS NULL",
                (title, conversation_id, user_id),
            )
            return cur.rowcount > 0

    async def soft_delete(self, *, user_id: int, conversation_id: int) -> bool:
        async with self._db.cursor() as cur:
            await cur.execute(
                "UPDATE conversation SET deleted_at = NOW() "
                "WHERE id = %s AND user_id = %s AND deleted_at IS NULL",
                (conversation_id, user_id),
            )
            return cur.rowcount > 0

    async def touch(self, conversation_id: int) -> None:
        async with self._db.cursor() as cur:
            await cur.execute(
                "UPDATE conversation SET updated_at = NOW() WHERE id = %s", (conversation_id,)
            )

    # ---------- 消息 ----------
    async def add_message(
        self,
        *,
        conversation_id: int,
        role: str,
        content: str,
        tokens: int | None = None,
        latency_ms: int | None = None,
        trace_id: str | None = None,
    ) -> int:
        async with self._db.cursor() as cur:
            await cur.execute(
                "INSERT INTO message (conversation_id, role, content, tokens, latency_ms, trace_id) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (conversation_id, role, content, tokens, latency_ms, trace_id),
            )
            return int(cur.lastrowid)

    async def list_messages(
        self, *, conversation_id: int, page: int, size: int
    ) -> tuple[list[dict[str, Any]], int]:
        offset = (page - 1) * size
        async with self._db.cursor() as cur:
            await cur.execute(
                "SELECT COUNT(*) AS c FROM message WHERE conversation_id = %s", (conversation_id,)
            )
            total = int((await cur.fetchone())["c"])
            await cur.execute(
                "SELECT id, role, content, tokens, latency_ms, trace_id, created_at "
                "FROM message WHERE conversation_id = %s ORDER BY id ASC LIMIT %s OFFSET %s",
                (conversation_id, size, offset),
            )
            rows = await cur.fetchall()
        return list(rows), total

    async def add_citations(self, *, message_id: int, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        sql = (
            "INSERT INTO citation (message_id, kb_file_id, chunk_id, page_no, url, snippet, score) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)"
        )
        args = [
            (
                message_id,
                it.get("kb_file_id"),
                it.get("chunk_id"),
                it.get("page_no"),
                it.get("url"),
                it.get("snippet", ""),
                it.get("score"),
            )
            for it in items
        ]
        async with self._db.cursor() as cur:
            await cur.executemany(sql, args)

    async def list_citations(self, *, message_id: int) -> list[dict[str, Any]]:
        async with self._db.cursor() as cur:
            await cur.execute(
                "SELECT kb_file_id, chunk_id, page_no, url, snippet, score "
                "FROM citation WHERE message_id = %s ORDER BY id ASC",
                (message_id,),
            )
            return list(await cur.fetchall())
