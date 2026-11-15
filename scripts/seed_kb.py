#!/usr/bin/env python3
"""P9-07：一键导入知识库种子（20 份原始文件）。

先 `scripts/seed_demo.py` 建好管理员账号并启动服务，然后：
    /hy-tmp/campus/venvs/web/bin/python scripts/seed_kb.py

文件与元数据来自 `data/kb_seed/manifest.json`；上传后回填 topics，保证主题过滤
在全新部署上也生效。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import aiomysql
import httpx

BASE = "http://127.0.0.1:8080"
ROOT = Path(__file__).resolve().parents[1]
SEED = Path(os.getenv("DATA_ROOT", "/hy-tmp/campus")) / "data" / "kb_seed"
if not (SEED / "manifest.json").is_file():
    SEED = ROOT / "data" / "kb_seed"


def env() -> dict[str, str]:
    values = {}
    for line in (Path(__file__).resolve().parents[1] / "backend" / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip()
    return values


def main() -> int:
    manifest = json.loads((SEED / "manifest.json").read_text(encoding="utf-8"))
    cfg = env()
    with httpx.Client(timeout=180) as client:
        login = client.post(BASE + "/api/v1/auth/login", json={"username": "admin", "password": "Admin@12345"})
        login.raise_for_status()
        headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}
        existing = {
            item["filename"]
            for item in client.get(BASE + "/api/v1/kb/files", params={"size": 100}, headers=headers).json()["data"]["items"]
        }
        pending: dict[str, int] = {}
        for item in manifest:
            name = item["filename"]
            path = SEED / "files" / name
            if not path.is_file():
                print("MISSING", name)
                continue
            if name in existing:
                print("SKIP", name)
                continue
            data = {"source_dept": item.get("source_dept") or "种子导入"}
            for key in ("source_url", "effective_from", "effective_to"):
                if item.get(key):
                    data[key] = item[key]
            with open(path, "rb") as handle:
                resp = client.post(
                    BASE + "/api/v1/kb/files",
                    headers=headers,
                    files={"file": (name, handle, "application/octet-stream")},
                    data=data,
                )
            if resp.status_code != 200:
                print("FAIL_UPLOAD", name, resp.status_code, resp.text[:120])
                continue
            pending[name] = resp.json()["data"]["id"]
            print("UPLOAD", name, pending[name])

        deadline = time.time() + 900
        while pending and time.time() < deadline:
            items = client.get(BASE + "/api/v1/kb/files", params={"size": 100}, headers=headers).json()["data"]["items"]
            by_id = {item["id"]: item for item in items}
            done = [name for name, file_id in pending.items() if by_id.get(file_id, {}).get("parse_status") in ("success", "failed")]
            for name in done:
                status = by_id[pending[name]]["parse_status"]
                print("PARSE", name, status)
                pending.pop(name, None)
            if pending:
                time.sleep(3)
        if pending:
            print("TIMEOUT", list(pending))
            return 1

    # 回填 topics：迁移 0005 在空库上不会命中任何行，种子导入后必须补一次
    import asyncio

    async def backfill():
        conn = await aiomysql.connect(
            host=cfg.get("MYSQL_HOST", "127.0.0.1"),
            port=int(cfg.get("MYSQL_PORT", "3306")),
            user=cfg["MYSQL_USER"],
            password=cfg["MYSQL_PASSWORD"],
            db=cfg["MYSQL_DB"],
            autocommit=True,
            charset="utf8mb4",
        )
        try:
            async with conn.cursor() as cur:
                for item in manifest:
                    if item.get("topics"):
                        await cur.execute("UPDATE kb_file SET topics=%s WHERE filename=%s", (item["topics"], item["filename"]))
        finally:
            conn.close()

    asyncio.run(backfill())
    print("DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
