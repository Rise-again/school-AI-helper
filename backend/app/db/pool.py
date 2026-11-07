"""MySQL 连接池。

- 单 worker 部署，池大小不需要很大（默认 1–10）。
- autocommit=True：单语句自动提交；需要原子性时用 transaction()。
- 连接失败不阻止进程启动（方便本地先起服务再起库），由 /readyz 反映真实状态。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import aiomysql

from app.core.config import Settings


class Database:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pool: aiomysql.Pool | None = None
        self.last_error: str | None = None

    @property
    def connected(self) -> bool:
        return self._pool is not None

    async def connect(self) -> None:
        s = self._settings
        self._pool = await aiomysql.create_pool(
            host=s.mysql_host,
            port=s.mysql_port,
            user=s.mysql_user,
            password=s.mysql_password,
            db=s.mysql_db,
            minsize=s.mysql_pool_min,
            maxsize=s.mysql_pool_max,
            autocommit=True,
            charset="utf8mb4",
            cursorclass=aiomysql.DictCursor,
            connect_timeout=5,
            pool_recycle=1800,
        )
        self.last_error = None

    async def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            await self._pool.wait_closed()
            self._pool = None

    @asynccontextmanager
    async def cursor(self) -> AsyncIterator[aiomysql.DictCursor]:
        if self._pool is None:
            raise RuntimeError("数据库连接池未初始化")
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                yield cur

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiomysql.DictCursor]:
        """多语句原子操作：异常回滚，正常提交。"""
        if self._pool is None:
            raise RuntimeError("数据库连接池未初始化")
        async with self._pool.acquire() as conn:
            await conn.begin()
            try:
                async with conn.cursor() as cur:
                    yield cur
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

    async def ping(self) -> bool:
        try:
            async with self.cursor() as cur:
                await cur.execute("SELECT 1 AS ok")
                await cur.fetchone()
            return True
        except Exception as exc:  # noqa: BLE001 - 任何异常都表示不可用
            self.last_error = f"{exc.__class__.__name__}: {exc}"
            return False

    async def scalar(self, sql: str, args: tuple[Any, ...] = ()) -> Any:
        async with self.cursor() as cur:
            await cur.execute(sql, args)
            row = await cur.fetchone()
        if row is None:
            return None
        return next(iter(row.values()))
