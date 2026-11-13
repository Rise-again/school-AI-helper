"""外网搜索结果的缓存读写（search_cache 表）。"""

from __future__ import annotations

import json
from typing import Any

from app.db.pool import Database


class SearchCacheRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, key: str, source: str = "anysearch") -> list[dict[str, Any]] | None:
        sql = (
            "SELECT result_json FROM search_cache "
            "WHERE query_hash=%s AND source=%s AND expires_at > NOW() LIMIT 1"
        )
        async with self._db.cursor() as cur:
            await cur.execute(sql, (key, source))
            row = await cur.fetchone()
        if not row:
            return None
        raw = row["result_json"]
        try:
            return json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            return None

    async def consume_daily(self, key: str, limit: int) -> bool:
        """占用一次全局配额；超限返回 False。按自然日计数。"""
        async with self._db.cursor() as cur:
            await cur.execute(
                "INSERT INTO api_quota (user_key, quota_date, used) VALUES (%s, CURDATE(), 1) "
                "ON DUPLICATE KEY UPDATE used = used + 1",
                (key,),
            )
            await cur.execute(
                "SELECT used FROM api_quota WHERE user_key=%s AND quota_date=CURDATE()", (key,)
            )
            row = await cur.fetchone()
        return bool(row) and int(row["used"]) <= limit

    async def today_usage(self, key: str) -> int:
        async with self._db.cursor() as cur:
            await cur.execute(
                "SELECT used FROM api_quota WHERE user_key=%s AND quota_date=CURDATE()", (key,)
            )
            row = await cur.fetchone()
        return int(row["used"]) if row else 0

    async def put(self, key: str, payload: list[dict[str, Any]], *, hours: int = 24, source: str = "anysearch") -> None:
        sql = (
            "INSERT INTO search_cache (query_hash, source, result_json, expires_at) "
            "VALUES (%s, %s, %s, DATE_ADD(NOW(), INTERVAL %s HOUR)) "
            "ON DUPLICATE KEY UPDATE result_json=VALUES(result_json), expires_at=VALUES(expires_at)"
        )
        async with self._db.cursor() as cur:
            await cur.execute(sql, (key, source, json.dumps(payload, ensure_ascii=False), hours))
