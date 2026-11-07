#!/usr/bin/env python3
"""生成脱敏演示账号（可重复执行，按用户名覆盖口令）。

用法：python scripts/seed_demo.py

生产环境请勿使用这里的口令；演示前把 .env 里的 JWT_SECRET 也换掉。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import aiomysql

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402

USERS = [
    {
        "username": "admin",
        "password": "Admin@12345",
        "role": "admin",
        "profile": None,
    },
    {
        "username": "20230001",
        "password": "Student@123",
        "role": "student",
        "profile": {
            "student_no": "20230001",
            "name": "张三",
            "college": "计算机科学与技术学院",
            "major": "计算机科学与技术",
            "grade": "2023",
        },
    },
    {
        "username": "20230002",
        "password": "Student@123",
        "role": "student",
        "profile": {
            "student_no": "20230002",
            "name": "李四",
            "college": "旅游学院",
            "major": "旅游管理",
            "grade": "2023",
        },
    },
]


async def main() -> int:
    settings = get_settings()
    try:
        conn = await aiomysql.connect(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=settings.mysql_password,
            db=settings.mysql_db,
            autocommit=True,
            charset="utf8mb4",
            cursorclass=aiomysql.DictCursor,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"连不上数据库（{settings.mysql_db}）：{exc}")
        print("先确认 MySQL 已启动，并执行过 python scripts/migrate.py")
        return 2

    try:
        async with conn.cursor() as cur:
            for user in USERS:
                await cur.execute(
                    "INSERT INTO user_account (username, role, password_hash) "
                    "VALUES (%s, %s, %s) "
                    "ON DUPLICATE KEY UPDATE role = VALUES(role), "
                    "password_hash = VALUES(password_hash), status = 'active', "
                    "fail_count = 0, locked_until = NULL",
                    (user["username"], user["role"], hash_password(user["password"])),
                )
                await cur.execute(
                    "SELECT id FROM user_account WHERE username = %s", (user["username"],)
                )
                user_id = (await cur.fetchone())["id"]

                profile = user["profile"]
                if profile:
                    await cur.execute(
                        "INSERT INTO student_profile "
                        "(user_id, student_no, name, college, major, grade) "
                        "VALUES (%s, %s, %s, %s, %s, %s) "
                        "ON DUPLICATE KEY UPDATE name = VALUES(name), "
                        "college = VALUES(college), major = VALUES(major), grade = VALUES(grade)",
                        (
                            user_id,
                            profile["student_no"],
                            profile["name"],
                            profile["college"],
                            profile["major"],
                            profile["grade"],
                        ),
                    )
                print(f"  写入 {user['role']:<7} {user['username']}")
        print("\n演示账号：")
        for user in USERS:
            print(f"  {user['role']:<7} {user['username']:<10} {user['password']}")
        print("\n注意：这批口令仅供本地演示，上线前必须更换。")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
