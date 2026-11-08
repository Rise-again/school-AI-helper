#!/usr/bin/env bash
# 下载模型权重（可从 ModelScope 镜像拉取，国内网络友好）
#
#   bash scripts/fetch_models.sh
#   MODEL_DIR=/data/models bash scripts/fetch_models.sh
#
# 已存在的模型会跳过，可重复执行。

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${VENV_DIR:-/hy-tmp/campus/venvs}"
MODEL_DIR="${MODEL_DIR:-/hy-tmp/campus/models}"
CLI="$VENV_DIR/dl/bin/modelscope"

[ -x "$CLI" ] || { echo "缺少下载环境：$CLI（先跑 install.sh）" >&2; exit 1; }
mkdir -p "$MODEL_DIR"

# 本地目录名 -> ModelScope 模型 ID
declare -A MODELS=(
  ["qwen2.5-7b-instruct"]="Qwen/Qwen2.5-7B-Instruct"
  ["bge-large-zh-v1.5"]="BAAI/bge-large-zh-v1.5"
  ["bge-reranker-v2-m3"]="BAAI/bge-reranker-v2-m3"
)
ORDER=(qwen2.5-7b-instruct bge-large-zh-v1.5 bge-reranker-v2-m3)

for name in "${ORDER[@]}"; do
  target="$MODEL_DIR/$name"
  if [ -f "$target/config.json" ]; then
    echo "  ✓ $name 已存在，跳过"
    continue
  fi
  echo "  ↓ 下载 $name（${MODELS[$name]}）"
  "$CLI" download --model "${MODELS[$name]}" --local_dir "$target"
  [ -f "$target/config.json" ] || { echo "下载失败：$name" >&2; exit 1; }
  echo "  ✓ $name 完成"
done

echo "模型目录：$MODEL_DIR"
du -sh "$MODEL_DIR"/* 2>/dev/null || true
