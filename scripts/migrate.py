#!/usr/bin/env python3
"""数据库迁移执行器。

用法：
    python scripts/migrate.py            # 应用所有未执行的迁移
    python scripts/migrate.py --check    # 只列出待执行的迁移，不改库

约定：migrations/000N_xxx.sql，文件名前缀为版本号；执行后写入 schema_version。
注意：MySQL 的 DDL 会隐式提交，所以每个文件执行完立即记版本；中途失败需人工确认后重跑。
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

import aiomysql
from aiomysql.constants import CLIENT

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402

MIGRATIONS_DIR = ROOT / "migrations"
_DB_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


async def _connect(settings, with_db: bool):
    kwargs = dict(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        autocommit=True,
        charset="utf8mb4",
        client_flag=CLIENT.MULTI_STATEMENTS,
    )
    if with_db:
        kwargs["db"] = settings.mysql_db
    return await aiomysql.connect(**kwargs)


async def _exec_script(cursor, sql: str) -> None:
    await cursor.execute(sql)
    while await cursor.nextset():
        pass


def _pending_versions(applied: set[str]) -> list[Path]:
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    pending = []
    for path in files:
        version = path.stem.split("_", 1)[0]
        if version not in applied:
            pending.append(path)
    return pending


async def run(check_only: bool) -> int:
    settings = get_settings()
    if not _DB_NAME_RE.match(settings.mysql_db):
        print(f"库名不合法：{settings.mysql_db!r}")
        return 2

    try:
        conn = await _connect(settings, with_db=False)
    except Exception as exc:  # noqa: BLE001 - 连接失败要给可读提示
        print(f"连不上 MySQL（{settings.mysql_host}:{settings.mysql_port}）：{exc}")
        return 2

    try:
        async with conn.cursor() as cur:
            if not check_only:
                await cur.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{settings.mysql_db}` "
                    "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
                )
            await cur.execute(f"USE `{settings.mysql_db}`")
            await cur.execute(
                "CREATE TABLE IF NOT EXISTS schema_version ("
                "version VARCHAR(32) NOT NULL PRIMARY KEY, "
                "applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            await cur.execute("SELECT version FROM schema_version")
            applied = {row[0] for row in await cur.fetchall()}

        pending = _pending_versions(applied)
        if not pending:
            print(f"无需迁移，已应用 {len(applied)} 个版本。")
            return 0
        print(f"待执行 {len(pending)} 个：" + ", ".join(p.stem for p in pending))
        if check_only:
            return 0

        for path in pending:
            version = path.stem.split("_", 1)[0]
            print(f"→ 执行 {path.name} ...", end="", flush=True)
            async with conn.cursor() as cur:
                await _exec_script(cur, path.read_text(encoding="utf-8"))
                await cur.execute(
                    "INSERT INTO schema_version (version) VALUES (%s)", (version,)
                )
            print(" ok")
        print("迁移完成。")
        return 0
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="数据库迁移")
    parser.add_argument("--check", action="store_true", help="只检查，不执行")
    args = parser.parse_args()
    return asyncio.run(run(args.check))


if __name__ == "__main__":
    raise SystemExit(main())
