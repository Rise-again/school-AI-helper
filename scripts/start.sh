#!/usr/bin/env bash
# 启动三个服务：vLLM(8001) → model-service(8002) → 后端(8080)
#
#   bash scripts/start.sh          # 全部启动（已在跑的会跳过）
#   bash scripts/start.sh backend  # 只启后端
#
# 进程信息写入 $DATA_ROOT/run/*.pid，日志在 $DATA_ROOT/logs/

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_ROOT="${DATA_ROOT:-/hy-tmp/campus}"
VENV_DIR="$DATA_ROOT/venvs"
MODEL_DIR="$DATA_ROOT/models"
LOG_DIR="$DATA_ROOT/logs"
RUN_DIR="$DATA_ROOT/run"
mkdir -p "$LOG_DIR" "$RUN_DIR"

TARGET="${1:-all}"

LLM_PORT="${LLM_PORT:-8001}"
MODEL_PORT="${MODEL_PORT:-8002}"
APP_PORT="${APP_PORT:-8080}"
GPU_MEM_UTIL="${GPU_MEM_UTIL:-0.70}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-4096}"
MAX_NUM_SEQS="${MAX_NUM_SEQS:-8}"

running() {  # $1 = pidfile
  local pidfile="$RUN_DIR/$1.pid"
  [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null
}

wait_http() {  # $1 = url, $2 = 描述, $3 = 超时秒
  local url="$1" label="$2" timeout="${3:-120}" i=0
  while [ "$i" -lt "$timeout" ]; do
    if curl -fsS -m 2 "$url" >/dev/null 2>&1; then
      echo "  ✓ $label 就绪"
      return 0
    fi
    i=$((i + 3)); sleep 3
  done
  echo "  ✗ $label 超时（看 $LOG_DIR）" >&2
  return 1
}

start_vllm() {
  if running vllm; then echo "  · vLLM 已在运行"; return 0; fi
  echo "  → 启动 vLLM（首次加载 1–3 分钟）"
  setsid nohup "$VENV_DIR/vllm/bin/vllm" serve "$MODEL_DIR/qwen2.5-7b-instruct" \
    --served-model-name qwen2.5-7b-instruct \
    --host 127.0.0.1 --port "$LLM_PORT" \
    --gpu-memory-utilization "$GPU_MEM_UTIL" \
    --max-model-len "$MAX_MODEL_LEN" \
    --max-num-seqs "$MAX_NUM_SEQS" \
    --enforce-eager \
    > "$LOG_DIR/vllm.log" 2>&1 < /dev/null &
  echo $! > "$RUN_DIR/vllm.pid"
  wait_http "http://127.0.0.1:$LLM_PORT/v1/models" "vLLM" 180
}

start_models() {
  if running models; then echo "  · model-service 已在运行"; return 0; fi
  echo "  → 启动 model-service（模型惰性加载）"
  cd "$REPO_ROOT/model_service"
  BGE_EMBED_PATH="$MODEL_DIR/bge-large-zh-v1.5" \
  BGE_RERANK_PATH="$MODEL_DIR/bge-reranker-v2-m3" \
  MODEL_DEVICE="${MODEL_DEVICE:-cuda}" \
  setsid nohup "$VENV_DIR/models/bin/uvicorn" app:create_app --factory \
    --host 127.0.0.1 --port "$MODEL_PORT" \
    > "$LOG_DIR/model-service.log" 2>&1 < /dev/null &
  echo $! > "$RUN_DIR/models.pid"
  wait_http "http://127.0.0.1:$MODEL_PORT/healthz" "model-service" 60
}

start_backend() {
  if running backend; then echo "  · 后端已在运行"; return 0; fi
  echo "  → 启动后端"
  cd "$REPO_ROOT/backend"
  setsid nohup "$VENV_DIR/web/bin/uvicorn" app.main:create_app --factory \
    --host 0.0.0.0 --port "$APP_PORT" \
    --proxy-headers --forwarded-allow-ips='*' \
    > "$LOG_DIR/backend.log" 2>&1 < /dev/null &
  echo $! > "$RUN_DIR/backend.pid"
  wait_http "http://127.0.0.1:$APP_PORT/healthz" "后端" 60
  curl -fsS "http://127.0.0.1:$APP_PORT/readyz" || echo "  ! readyz 未全绿，稍等模型加载"
}

case "$TARGET" in
  all)      start_vllm; start_models; start_backend ;;
  vllm)     start_vllm ;;
  models)   start_models ;;
  backend)  start_backend ;;
  *) echo "用法：bash scripts/start.sh [all|vllm|models|backend]" >&2; exit 2 ;;
esac

echo
echo "访问：http://127.0.0.1:$APP_PORT/docs"
