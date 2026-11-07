"""知识库文件 / 切片 / 解析任务的数据访问。"""

from __future__ import annotations

from typing import Any

from app.db.pool import Database


class KbRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    # ---------- 文件 ----------
    async def find_by_hash(self, file_hash: str) -> dict[str, Any] | None:
        async with self._db.cursor() as cur:
            await cur.execute(
                "SELECT * FROM kb_file WHERE file_hash = %s AND deleted_at IS NULL", (file_hash,)
            )
            return await cur.fetchone()

    async def create_file(
        self,
        *,
        filename: str,
        file_hash: str,
        file_type: str,
        size_bytes: int,
        source_dept: str | None,
        effective_from: str | None,
        effective_to: str | None,
        uploaded_by: int | None,
    ) -> int:
        async with self._db.cursor() as cur:
            await cur.execute(
                "INSERT INTO kb_file (filename, file_hash, file_type, size_bytes, source_dept, "
                "effective_from, effective_to, uploaded_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    filename,
                    file_hash,
                    file_type,
                    size_bytes,
                    source_dept,
                    effective_from,
                    effective_to,
                    uploaded_by,
                ),
            )
            return int(cur.lastrowid)

    async def get_file(self, file_id: int) -> dict[str, Any] | None:
        async with self._db.cursor() as cur:
            await cur.execute("SELECT * FROM kb_file WHERE id = %s", (file_id,))
            return await cur.fetchone()

    async def list_files(
        self, *, page: int, size: int, status: str | None = None
    ) -> tuple[list[dict[str, Any]], int]:
        where = "WHERE deleted_at IS NULL"
        args: list[Any] = []
        if status:
            where += " AND parse_status = %s"
            args.append(status)
        async with self._db.cursor() as cur:
            await cur.execute(f"SELECT COUNT(*) AS c FROM kb_file {where}", tuple(args))
            total = int((await cur.fetchone())["c"])
            await cur.execute(
                f"SELECT id, filename, file_type, size_bytes, parse_channel, source_dept, "
                f"effective_from, effective_to, parse_status, chunk_count, version, "
                f"uploaded_by, created_at, updated_at FROM kb_file {where} "
                f"ORDER BY id DESC LIMIT %s OFFSET %s",
                (*args, size, (page - 1) * size),
            )
            rows = await cur.fetchall()
        return list(rows), total

    async def update_status(
        self,
        file_id: int,
        *,
        status: str,
        channel: str | None = None,
        chunk_count: int | None = None,
    ) -> None:
        async with self._db.cursor() as cur:
            await cur.execute(
                "UPDATE kb_file SET parse_status = %s, "
                "parse_channel = COALESCE(%s, parse_channel), "
                "chunk_count = COALESCE(%s, chunk_count) WHERE id = %s",
                (status, channel, chunk_count, file_id),
            )

    async def soft_delete(self, file_id: int) -> bool:
        async with self._db.cursor() as cur:
            await cur.execute(
                "UPDATE kb_file SET deleted_at = NOW() WHERE id = %s AND deleted_at IS NULL", (file_id,)
            )
            return cur.rowcount > 0

    # ---------- 切片 ----------
    async def replace_chunks(self, file_id: int, rows: list[dict[str, Any]]) -> None:
        sql = (
            "INSERT INTO kb_chunk (kb_file_id, ordinal, content, token_count, vector_id, meta_json) "
            "VALUES (%s, %s, %s, %s, %s, %s)"
        )
        async with self._db.transaction() as cur:
            await cur.execute("DELETE FROM kb_chunk WHERE kb_file_id = %s", (file_id,))
            if rows:
                await cur.executemany(
                    sql,
                    [
                        (
                            file_id,
                            r["ordinal"],
                            r["content"],
                            r["token_count"],
                            r["vector_id"],
                            r["meta_json"],
                        )
                        for r in rows
                    ],
                )

    async def list_chunks(
        self, *, file_id: int, page: int, size: int
    ) -> tuple[list[dict[str, Any]], int]:
        async with self._db.cursor() as cur:
            await cur.execute("SELECT COUNT(*) AS c FROM kb_chunk WHERE kb_file_id = %s", (file_id,))
            total = int((await cur.fetchone())["c"])
            await cur.execute(
                "SELECT id, ordinal, content, token_count, vector_id, meta_json, created_at "
                "FROM kb_chunk WHERE kb_file_id = %s ORDER BY ordinal ASC LIMIT %s OFFSET %s",
                (file_id, size, (page - 1) * size),
            )
            rows = await cur.fetchall()
        return list(rows), total

    # ---------- 解析任务 ----------
    async def add_task(self, file_id: int, *, stage: str, status: str = "pending") -> int:
        async with self._db.cursor() as cur:
            await cur.execute(
                "INSERT INTO parse_task (kb_file_id, stage, status) VALUES (%s, %s, %s)",
                (file_id, stage, status),
            )
            return int(cur.lastrowid)

    async def start_task(self, task_id: int) -> None:
        async with self._db.cursor() as cur:
            await cur.execute(
                "UPDATE parse_task SET status = 'running', started_at = NOW() WHERE id = %s",
                (task_id,),
            )

    async def finish_task(self, task_id: int, *, status: str, error: str | None = None) -> None:
        async with self._db.cursor() as cur:
            await cur.execute(
                "UPDATE parse_task SET status = %s, error_text = %s, finished_at = NOW() WHERE id = %s",
                (status, error, task_id),
            )
