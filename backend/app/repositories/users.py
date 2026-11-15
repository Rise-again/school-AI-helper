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

    async def get_edu_binding(self, user_id: int) -> dict[str, Any] | None:
        """教务绑定信息（含密文，调用方负责解密，不要写进日志）。"""
        sql = (
            "SELECT student_no, edu_username, edu_cred_cipher, edu_bound_at "
            "FROM student_profile WHERE user_id = %s"
        )
        async with self._db.cursor() as cur:
            await cur.execute(sql, (user_id,))
            row = await cur.fetchone()
        if row:
            row["edu_cred_cipher"] = self._cipher_from_db(row.get("edu_cred_cipher"))
        return row

    @staticmethod
    def _cipher_from_db(value: Any) -> bytes | None:
        """兼容两种存法：新数据是 hex 字符串（aiomysql 对 bytes 参数有兼容问题），
        旧数据可能是原始 bytes；统一还原成原始密文字节。"""
        if value is None:
            return None
        if isinstance(value, str):
            return bytes.fromhex(value)
        if isinstance(value, (bytes, bytearray)):
            raw = bytes(value)
            try:
                return bytes.fromhex(raw.decode("ascii"))
            except (UnicodeDecodeError, ValueError):
                return raw
        return bytes(value)

    async def save_edu_binding(
        self, *, user_id: int, student_no: str, edu_username: str, cred_cipher: bytes
    ) -> None:
        sql = (
            "INSERT INTO student_profile (user_id, student_no, edu_username, edu_cred_cipher, edu_bound_at) "
            "VALUES (%s, %s, %s, %s, NOW()) "
            "ON DUPLICATE KEY UPDATE edu_username = VALUES(edu_username), "
            "edu_cred_cipher = VALUES(edu_cred_cipher), edu_bound_at = NOW()"
        )
        # aiomysql 0.3.2 + pymysql 2.2.8 对 bytes 参数会抛 TypeError，存 hex 字符串规避
        async with self._db.cursor() as cur:
            await cur.execute(sql, (user_id, student_no, edu_username, cred_cipher.hex()))

    async def clear_edu_binding(self, user_id: int) -> None:
        sql = (
            "UPDATE student_profile SET edu_username = NULL, edu_cred_cipher = NULL, "
            "edu_bound_at = NULL WHERE user_id = %s"
        )
        async with self._db.cursor() as cur:
            await cur.execute(sql, (user_id,))

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
