#!/usr/bin/env python3
"""从 Hugging Face 下载 P4 LoRA adapter（campus-lora）。

用法（服务器）：
    /hy-tmp/campus/venvs/dl/bin/python scripts/fetch_adapter.py \
        --repo <hf-user>/campus-lora-p4-v1

或先写入 backend/.env：
    ADAPTER_REPO=<hf-user>/campus-lora-p4-v1
    ADAPTER_REVISION=<commit-hash>   # 可选，建议固定
然后：
    /hy-tmp/campus/venvs/dl/bin/python scripts/fetch_adapter.py

国内服务器可加 `--endpoint https://hf-mirror.com` 或设 `HF_ENDPOINT`。
私有仓库设 `HF_TOKEN` 环境变量。
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET_DEFAULT = Path(os.getenv("DATA_ROOT", "/hy-tmp/campus")) / "data" / "sft" / "output"

PATTERNS = [
    "adapter_config.json",
    "adapter_model.safetensors",
    "adapter_model.bin",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
    "merges.txt",
    "added_tokens.json",
    "special_tokens_map.json",
    "chat_template.jinja",
    "README.md",
]


def read_env() -> dict[str, str]:
    path = ROOT / "backend" / ".env"
    values: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values


def main() -> int:
    env = read_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=os.getenv("ADAPTER_REPO") or env.get("ADAPTER_REPO", ""))
    parser.add_argument("--revision", default=os.getenv("ADAPTER_REVISION") or env.get("ADAPTER_REVISION", ""))
    parser.add_argument("--target", default=str(TARGET_DEFAULT))
    parser.add_argument("--endpoint", default=os.getenv("HF_ENDPOINT", ""))
    args = parser.parse_args()

    if not args.repo:
        print("缺少 repo：传 --repo 或在 backend/.env 写 ADAPTER_REPO=<user>/<repo>")
        return 2
    if args.endpoint:
        os.environ["HF_ENDPOINT"] = args.endpoint
    target = Path(args.target)
    target.mkdir(parents=True, exist_ok=True)

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("缺少 huggingface_hub：/hy-tmp/campus/venvs/dl/bin/pip install huggingface_hub")
        return 2

    print(f"下载 {args.repo}@{args.revision or 'main'} -> {target}")
    snapshot_download(
        repo_id=args.repo,
        revision=args.revision or None,
        local_dir=str(target),
        allow_patterns=PATTERNS,
    )
    config = target / "adapter_config.json"
    weights = target / "adapter_model.safetensors"
    if not config.is_file() or not weights.is_file():
        print("下载后缺少 adapter_config.json / adapter_model.safetensors，请检查仓库内容")
        return 1
    print("adapter 就绪。确认 backend/.env 中 LLM_MODEL=campus-lora，然后 bash scripts/start.sh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
