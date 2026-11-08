#!/usr/bin/env bash
# 一键安装：Ubuntu 22.04 + NVIDIA GPU
#
#   bash install.sh                 # 全量（系统依赖 + 三个环境 + 模型 + 数据库）
#   bash install.sh --skip-models   # 不下载约 20GB 模型权重
#   bash install.sh --skip-apt      # 不装系统包（已自备 MySQL/Python 时）
#   bash install.sh --skip-db       # 不初始化数据库
#   DATA_ROOT=/data/campus bash install.sh
#
# 幂等：重复执行只补缺失的部分，不会覆盖已有 .env 与已装好的环境。

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_ROOT="${DATA_ROOT:-/hy-tmp/campus}"
VENV_DIR="$DATA_ROOT/venvs"
MODEL_DIR="$DATA_ROOT/models"
LOG_DIR="$DATA_ROOT/logs"
RUN_DIR="$DATA_ROOT/run"

SKIP_MODELS=0
SKIP_APT=0
SKIP_DB=0

for arg in "$@"; do
  case "$arg" in
    --skip-models) SKIP_MODELS=1 ;;
    --skip-apt)    SKIP_APT=1 ;;
    --skip-db)     SKIP_DB=1 ;;
    -h|--help)     sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "未知参数：$arg（--help 查看用法）" >&2; exit 2 ;;
  esac
done

step() { printf '\n\033[1;36m[%s/7] %s\033[0m\n' "$1" "$2"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$1"; }
die()  { printf '\033[31m✗ %s\033[0m\n' "$1" >&2; exit 1; }

# ---------------------------------------------------------------- 1 环境检查
step 1 "环境检查"
[ "$(id -u)" -eq 0 ] || warn "当前不是 root，安装系统包时可能失败"
command -v python3 >/dev/null || die "缺少 python3"
PY_VER="$(python3 -V 2>&1 | awk '{print $2}')"
PY_MAJOR_MINOR="$(python3 -c 'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
python3 - <<'PY' || die "Python 版本过低，需要 3.10+"
import sys
assert sys.version_info >= (3, 10), sys.version
PY
ok "Python $PY_VER"

if command -v nvidia-smi >/dev/null; then
  GPU_MEM="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1)"
  DRIVER="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1)"
  ok "GPU $(nvidia-smi --query-gpu=name --format=csv,noheader | head -1) / ${GPU_MEM}MiB / 驱动 $DRIVER"
  [ "${GPU_MEM:-0}" -ge 20000 ] || warn "显存 <20GB，7B 模型可能 OOM（本项目按 24GB 调参）"
else
  die "没有检测到 NVIDIA GPU。本项目所有模型都在本机运行，必须要有 GPU"
fi

mkdir -p "$VENV_DIR" "$MODEL_DIR" "$LOG_DIR" "$RUN_DIR"
chmod 700 "$DATA_ROOT" 2>/dev/null || true
FREE_GB="$(df -BG --output=avail "$DATA_ROOT" | tail -1 | tr -dc '0-9')"
[ "$FREE_GB" -ge 40 ] || warn "$DATA_ROOT 只剩 ${FREE_GB}GB，建议 ≥40GB（模型约 20GB）"
ok "数据目录 $DATA_ROOT"

# ---------------------------------------------------------------- 2 系统依赖
step 2 "系统依赖"
if [ "$SKIP_APT" -eq 1 ]; then
  warn "按参数跳过 apt"
else
  if command -v apt-get >/dev/null; then
    MISSING=""
    command -v mysql      >/dev/null || MISSING="$MISSING mysql-server"
    command -v virtualenv >/dev/null || python3 -c 'import virtualenv' 2>/dev/null || MISSING="$MISSING python3-pip"
    dpkg -s build-essential >/dev/null 2>&1 || MISSING="$MISSING build-essential"
    if [ -n "$MISSING" ]; then
      echo "  安装：$MISSING"
      DEBIAN_FRONTEND=noninteractive apt-get update -qq
      DEBIAN_FRONTEND=noninteractive apt-get install -y -qq $MISSING
    fi
    python3 -c 'import virtualenv' 2>/dev/null || pip3 install -q virtualenv
    ok "系统包就绪"
  else
    warn "非 apt 系系统，请自行确保 mysql-server 与 python3-pip 已安装"
  fi
fi

# ---------------------------------------------------------------- 3 虚拟环境
step 3 "创建三个虚拟环境（web / vllm / models）"
# 说明：镜像可能缺 ensurepip，python3 -m venv 会失败，统一用 virtualenv
for env_name in web vllm models; do
  target="$VENV_DIR/$env_name"
  if [ -x "$target/bin/python" ] && "$target/bin/python" -m pip --version >/dev/null 2>&1; then
    ok "$env_name 已存在"
  else
    rm -rf "$target"
    python3 -m virtualenv -q "$target" -p python3
    ok "$env_name 创建完成（$( "$target/bin/python" -V 2>&1)）"
  fi
done

# ---------------------------------------------------------------- 4 Python 依赖
step 4 "安装 Python 依赖（首次约 10–15 分钟）"
cd "$REPO_ROOT"

echo "  → web（后端）"
"$VENV_DIR/web/bin/pip" install -q -U pip
"$VENV_DIR/web/bin/pip" install -q -r backend/requirements-linux.txt

echo "  → models（bge + OCR）"
"$VENV_DIR/models/bin/pip" install -q -U pip
# torch 显式安装：不依赖宿主机已装，保证换机器可复现（cu128，适配驱动 ≥525）
"$VENV_DIR/models/bin/pip" install -q "torch==2.9.1"
"$VENV_DIR/models/bin/pip" install -q \
  "FlagEmbedding==1.4.2" "paddlepaddle==3.3.1" "paddleocr==3.7.0" \
  "pypdfium2" "pillow" "fastapi==0.162.0" "uvicorn==0.54.0" "pydantic==2.14.3" \
  "httpx==0.28.1" "python-multipart==0.0.32"

echo "  → vllm（推理）"
"$VENV_DIR/vllm/bin/pip" install -q -U pip
# 关键：vllm 0.11 配 torch 2.8(cu128)；0.31 起是 cu130，驱动 <580 跑不起来
"$VENV_DIR/vllm/bin/pip" install -q "vllm==0.11.0"
"$VENV_DIR/vllm/bin/pip" install -q "transformers==4.57.1"

echo "  → 下载环境（模型下载用）"
[ -x "$VENV_DIR/dl/bin/python" ] || python3 -m virtualenv -q "$VENV_DIR/dl" -p python3
"$VENV_DIR/dl/bin/pip" install -q -U pip modelscope
ok "依赖安装完成"

# ---------------------------------------------------------------- 5 模型权重
step 5 "模型权重"
if [ "$SKIP_MODELS" -eq 1 ]; then
  warn "按参数跳过；之后可运行 bash scripts/fetch_models.sh"
else
  VENV_DIR="$VENV_DIR" MODEL_DIR="$MODEL_DIR" bash "$REPO_ROOT/scripts/fetch_models.sh"
fi

# ---------------------------------------------------------------- 6 数据库
step 6 "数据库与配置"
if [ "$SKIP_DB" -eq 1 ]; then
  warn "按参数跳过数据库初始化"
else
  if ! mysqladmin ping >/dev/null 2>&1; then
    echo "  启动 MySQL"
    service mysql start >/dev/null 2>&1 || mysqld_safe --skip-networking=0 >/dev/null 2>&1 &
    for _ in $(seq 1 30); do mysqladmin ping >/dev/null 2>&1 && break; sleep 1; done
  fi
  mysqladmin ping >/dev/null 2>&1 || die "MySQL 没起来，检查 /var/log/mysql/error.log"
  ok "MySQL 运行中"

  if [ -f backend/.env ]; then
    ok "backend/.env 已存在，保留不动"
    DB_PASSWORD="$(grep -E '^MYSQL_PASSWORD=' backend/.env | cut -d= -f2-)"
  else
    DB_PASSWORD="$(openssl rand -hex 16 2>/dev/null || python3 -c 'import secrets;print(secrets.token_hex(16))')"
    mysql -uroot <<SQL
CREATE DATABASE IF NOT EXISTS campus_assistant DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER IF NOT EXISTS 'campus'@'127.0.0.1' IDENTIFIED BY '${DB_PASSWORD}';
ALTER USER 'campus'@'127.0.0.1' IDENTIFIED BY '${DB_PASSWORD}';
GRANT ALL PRIVILEGES ON campus_assistant.* TO 'campus'@'127.0.0.1';
FLUSH PRIVILEGES;
SQL
    DATA_ROOT="$DATA_ROOT" MYSQL_PASSWORD="$DB_PASSWORD" python3 scripts/gen_env.py --output backend/.env
    ok "数据库与 backend/.env 已创建"
  fi

  echo "  执行迁移与演示数据"
  PYTHONPATH=backend "$VENV_DIR/web/bin/python" scripts/migrate.py
  PYTHONPATH=backend "$VENV_DIR/web/bin/python" scripts/seed_demo.py | tail -6
fi

# ---------------------------------------------------------------- 7 自检
step 7 "自检"
DATA_ROOT="$DATA_ROOT" "$VENV_DIR/web/bin/python" - <<'PY'
import os, socket, sys
from pathlib import Path
root = Path(os.environ["DATA_ROOT"])
checks = []
checks.append(("数据目录可写", os.access(root, os.W_OK)))
for name in ("web", "vllm", "models"):
    checks.append((f"环境 {name}", (root / "venvs" / name / "bin" / "python").exists()))
for name in ("qwen2.5-7b-instruct", "bge-large-zh-v1.5", "bge-reranker-v2-m3"):
    checks.append((f"模型 {name}", (root / "models" / name / "config.json").exists()))
s = socket.socket()
try:
    s.settimeout(2); s.connect(("127.0.0.1", 3306)); checks.append(("MySQL 端口", True))
except OSError:
    checks.append(("MySQL 端口", False))
finally:
    s.close()
for label, ok in checks:
    print(f"  {'✓' if ok else '✗'} {label}")
sys.exit(0 if all(ok for _, ok in checks) else 1)
PY

cat <<EOF

$(printf '\033[1;32m安装完成\033[0m')

启动服务：
  bash scripts/start.sh

检查运行状态：
  curl -s http://127.0.0.1:8080/readyz

演示账号（上线前务必修改）：
  admin / Admin@12345     管理员
  20230001 / Student@123  学生

日志目录：$LOG_DIR
EOF
