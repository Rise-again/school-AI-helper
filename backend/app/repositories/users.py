"""账号与学生档案的数据访问。只写 SQL，不做业务判断。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.db.pool import Database


class UserRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_by_username(self, username: str) -> dict[str, Any] | None:
        sql = (
            "SELECT id, username, role, password_hash, status, fail_count, locked_until "
            "FROM user_account WHERE username = %s"
        )
        async with self._db.cursor() as cur:
            await cur.execute(sql, (username,))
            return await cur.fetchone()

    async def get_by_id(self, user_id: int) -> dict[str, Any] | None:
        sql = (
            "SELECT id, username, role, status, fail_count, locked_until, created_at "
            "FROM user_account WHERE id = %s"
        )
        async with self._db.cursor() as cur:
            await cur.execute(sql, (user_id,))
            return await cur.fetchone()

    async def create(self, *, username: str, password_hash: str, role: str) -> int:
        async with self._db.cursor() as cur:
            await cur.execute(
                "INSERT INTO user_account (username, role, password_hash) VALUES (%s, %s, %s)",
                (username, role, password_hash),
            )
            return int(cur.lastrowid)

    async def register_failure(self, user_id: int, *, threshold: int = 5, lock_minutes: int = 10) -> dict[str, Any]:
        """失败计数 +1；达到阈值则锁定。返回最新计数与锁定时间。"""
        sql = (
            "UPDATE user_account SET fail_count = fail_count + 1, "
            "locked_until = CASE WHEN fail_count + 1 >= %s "
            "THEN DATE_ADD(NOW(), INTERVAL %s MINUTE) ELSE locked_until END "
            "WHERE id = %s"
        )
        async with self._db.cursor() as cur:
            await cur.execute(sql, (threshold, lock_minutes, user_id))
            await cur.execute(
                "SELECT fail_count, locked_until FROM user_account WHERE id = %s", (user_id,)
            )
            row = await cur.fetchone()
        return row or {"fail_count": 0, "locked_until": None}

    async def reset_failure(self, user_id: int) -> None:
        async with self._db.cursor() as cur:
            await cur.execute(
                "UPDATE user_account SET fail_count = 0, locked_until = NULL WHERE id = %s",
                (user_id,),
            )

    async def get_profile(self, user_id: int) -> dict[str, Any] | None:
        sql = (
            "SELECT student_no, name, college, major, grade, edu_bound_at "
            "FROM student_profile WHERE user_id = %s"
        )
        async with self._db.cursor() as cur:
            await cur.execute(sql, (user_id,))
            return await cur.fetchone()

    async def count(self) -> int:
        return int(await self._db.scalar("SELECT COUNT(*) AS c FROM user_account") or 0)

    @staticmethod
    def is_locked(row: dict[str, Any]) -> tuple[bool, int]:
        """返回 (是否锁定, 剩余分钟)。锁定时间已过则视为未锁定。"""
        locked_until: datetime | None = row.get("locked_until")
        if not locked_until:
            return False, 0
        now = datetime.now(tz=locked_until.tzinfo) if locked_until.tzinfo else datetime.now()
        remain = int((locked_until - now).total_seconds() // 60) + 1
        return (remain > 0), max(remain, 0)
