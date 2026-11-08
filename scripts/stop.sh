#!/usr/bin/env bash
# 停止服务：bash scripts/stop.sh [all|vllm|models|backend]

set -euo pipefail

DATA_ROOT="${DATA_ROOT:-/hy-tmp/campus}"
RUN_DIR="$DATA_ROOT/run"

stop_one() {
  local name="$1" pidfile="$RUN_DIR/$1.pid"
  if [ -f "$pidfile" ]; then
    local pid; pid="$(cat "$pidfile")"
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      for _ in $(seq 1 10); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
      kill -9 "$pid" 2>/dev/null || true
      echo "  ✓ 已停止 $name"
    else
      echo "  · $name 未在运行"
    fi
    rm -f "$pidfile"
  else
    echo "  · $name 无 pid 文件"
  fi
}

case "${1:-all}" in
  all)     stop_one backend; stop_one models; stop_one vllm ;;
  vllm)    stop_one vllm ;;
  models)  stop_one models ;;
  backend) stop_one backend ;;
  *) echo "用法：bash scripts/stop.sh [all|vllm|models|backend]" >&2; exit 2 ;;
esac
