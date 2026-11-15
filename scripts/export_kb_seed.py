import asyncio
import json
import shutil
from pathlib import Path

import aiomysql

env = {}
for line in Path("/hy-tmp/campus/app/backend/.env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()


async def main():
    conn = await aiomysql.connect(
        host="127.0.0.1",
        port=3306,
        user=env["MYSQL_USER"],
        password=env["MYSQL_PASSWORD"],
        db=env["MYSQL_DB"],
        charset="utf8mb4",
        cursorclass=aiomysql.DictCursor,
    )
    out = Path("/tmp/kb_seed")
    shutil.rmtree(out, ignore_errors=True)
    (out / "files").mkdir(parents=True)
    manifest = []
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT filename,file_hash,file_type,source_dept,source_url,effective_from,effective_to,topics "
            "FROM kb_file WHERE deleted_at IS NULL ORDER BY id"
        )
        for row in await cur.fetchall():
            src = Path("/hy-tmp/campus/data/uploads") / f"{row['file_hash']}.{row['file_type']}"
            if not src.is_file():
                print("MISSING", row["filename"], src)
                continue
            shutil.copy2(src, out / "files" / row["filename"])
            manifest.append({k: (str(v) if v is not None else None) for k, v in row.items()})
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print("files", len(manifest))
    conn.close()


asyncio.run(main())
