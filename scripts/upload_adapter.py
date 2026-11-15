#!/usr/bin/env python3
"""上传 LoRA adapter 到 Hugging Face（不依赖 hf CLI / PATH）。

用法（Windows PowerShell）：
    py -m pip install -U huggingface_hub
    $env:HF_TOKEN="hf_xxx"        # 或运行后按提示粘贴
    py upload_adapter.py          # 自动用你的 HF 账号名，仓库名为 <账号>/campus-lora-p4-v1
    py upload_adapter.py --repo Rise-again/campus-lora-p4-v1   # 或显式指定

默认上传本文件同目录下的 `campus-lora-p4-v1` 文件夹。
上传成功会打印 commit sha，把它填到服务器 backend/.env 的 ADAPTER_REVISION。
"""

from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="", help="<user>/<repo>；留空则用 <你的HF用户名>/campus-lora-p4-v1")
    parser.add_argument("--folder", default=str(Path(__file__).resolve().parent / "campus-lora-p4-v1"))
    parser.add_argument("--private", action="store_true")
    args = parser.parse_args()

    folder = Path(args.folder)
    if not (folder / "adapter_config.json").is_file() or not (folder / "adapter_model.safetensors").is_file():
        print(f"目录不完整：{folder}（需要 adapter_config.json 与 adapter_model.safetensors）")
        return 2

    try:
        from huggingface_hub import HfApi
    except ImportError:
        print("缺少 huggingface_hub，请先运行：py -m pip install -U huggingface_hub")
        return 2

    token = os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN")
    if not token:
        token = getpass.getpass("HF token（write 权限，输入不显示）: ").strip()
    if not token:
        print("没有 token")
        return 2

    api = HfApi(token=token)
    try:
        who = api.whoami()
        username = who.get("name") or who.get("user")
    except Exception as exc:  # noqa: BLE001
        print(f"token 校验失败：{exc}")
        return 1

    repo_id = args.repo or f"{username}/campus-lora-p4-v1"
    print(f"仓库：{repo_id}（{'private' if args.private else 'public'}）")
    api.create_repo(repo_id=repo_id, repo_type="model", exist_ok=True, private=args.private)
    api.upload_folder(
        repo_id=repo_id,
        repo_type="model",
        folder_path=str(folder),
        commit_message="upload campus-lora-p4-v1 adapter",
    )
    info = api.repo_info(repo_id=repo_id, repo_type="model")
    print("上传完成")
    print("ADAPTER_REPO=" + repo_id)
    print("ADAPTER_REVISION=" + info.sha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
