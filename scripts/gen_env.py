#!/usr/bin/env python3
"""根据 .env.example 生成 backend/.env。

只做三件事：填随机密钥、按需改数据库口令、把相对路径换成绝对路径。
已存在且不是 --force 时不覆盖，避免把线上配置冲掉。

用法：
    python scripts/gen_env.py                      # 生成 backend/.env
    MYSQL_PASSWORD=xxx python scripts/gen_env.py   # 指定库口令（install.sh 用）
    python scripts/gen_env.py --force              # 强制覆盖
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 backend/.env")
    parser.add_argument("--template", default=str(ROOT / ".env.example"))
    parser.add_argument("--output", default=str(ROOT / "backend" / ".env"))
    parser.add_argument("--force", action="store_true", help="已存在也覆盖")
    args = parser.parse_args()

    template = Path(args.template)
    output = Path(args.output)
    if not template.is_file():
        print(f"模板不存在：{template}", file=sys.stderr)
        return 2
    if output.exists() and not args.force:
        print(f"已存在，跳过：{output}（要覆盖加 --force）")
        return 0

    text = template.read_text(encoding="utf-8")
    jwt_secret = secrets.token_hex(32)
    mysql_password = os.environ.get("MYSQL_PASSWORD") or secrets.token_hex(16)

    text = text.replace("__JWT_SECRET__", jwt_secret)
    text = text.replace("__MYSQL_PASSWORD__", mysql_password)

    # 相对路径改成绝对路径，避免从不同工作目录启动时数据落错地方
    data_root = os.environ.get("DATA_ROOT")
    if data_root:
        text = text.replace("CHROMA_DIR=data/chroma", f"CHROMA_DIR={data_root}/data/chroma")
        text = text.replace("UPLOAD_DIR=data/uploads", f"UPLOAD_DIR={data_root}/data/uploads")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    try:
        output.chmod(0o600)
    except OSError:
        pass

    print(f"已生成 {output}")
    if "__" in text.split("MYSQL_PASSWORD=")[1].split("\n")[0]:
        print("警告：模板里仍有未替换的占位符，请检查 .env.example", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
