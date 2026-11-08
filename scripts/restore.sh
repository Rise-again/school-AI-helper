#!/usr/bin/env bash
# 从个人数据恢复（换实例、/hy-tmp 被清空后使用）
#
#   bash scripts/restore.sh --timestamp 2026-11-08-1200          # 日常件（代码+数据+数据库）
#   bash scripts/restore.sh --timestamp 2026-11-08-1200 --full   # 连虚拟环境与自训模型一起
#
# 备份里通常不含公开基座模型：恢复时若发现缺失，会自动调 scripts/fetch_models.sh 重新下载。
#
# 流程：下载 → 停服务 → 旧目录改名备份 → 解包 → 恢复数据库 → 启动 → 自检
# 任何一步失败，脚本会尝试把旧目录改回来，不会留下半套环境。

set -euo pipefail

DATA_ROOT="${DATA_ROOT:-/hy-tmp/campus}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP=""
FULL=0

while [ $# -gt 0 ]; do
  case "$1" in
    --timestamp) STAMP="${2:-}"; shift 2 ;;
    --full)      FULL=1; shift ;;
    -h|--help)   sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done

ok()  { printf '  \033[32m✓\033[0m %s\n' "$1"; }
die() { printf '\033[31m✗ %s\033[0m\n' "$1" >&2; exit 1; }

[ -n "$STAMP" ] || die "缺少 --timestamp，例如 --timestamp 2026-11-08-1200"
command -v oss >/dev/null || die "缺少 oss 命令"
oss ls >/dev/null 2>&1 || die "oss 未登录，先执行 oss login"

OSS_ROOT="${OSS_ROOT:-oss://campus}"

STAGE="$DATA_ROOT/restore-$STAMP"
mkdir -p "$STAGE"
echo "恢复点：$STAMP（$([ "$FULL" -eq 1 ] && echo 全量 || echo 日常)）"

# ---------- 1 下载 ----------
echo "[1/6] 下载"
oss cp "$OSS_ROOT/db-$STAMP.sql.gz" "$STAGE/" >/dev/null 2>&1 || die "找不到 db-$STAMP.sql.gz"
oss cp "$OSS_ROOT/appdata-$STAMP.tar.gz" "$STAGE/" >/dev/null 2>&1 || true
if [ "$FULL" -eq 1 ]; then
  oss cp "$OSS_ROOT/venvs-$STAMP.tar.gz" "$STAGE/" >/dev/null 2>&1 || die "找不到 venvs-$STAMP.tar.gz"
  # 公开基座模型只有 --with-models 备份时才有，没有就走下载
  oss cp "$OSS_ROOT/models-$STAMP.tar.gz" "$STAGE/" >/dev/null 2>&1 || true
fi
oss cp "$OSS_ROOT/custom-$STAMP.tar.gz" "$STAGE/" >/dev/null 2>&1 || true
ok "下载完成（$(du -sh "$STAGE" | cut -f1)）"

# ---------- 2 停服务 ----------
echo "[2/6] 停止服务"
bash "$REPO_ROOT/scripts/stop.sh" >/dev/null 2>&1 || true
service mysql stop >/dev/null 2>&1 || true
ok "已停止"

# ---------- 3 旧目录改名（失败可回滚） ----------
echo "[3/6] 备份现有目录"
ROLLBACK=""
for d in venvs models; do
  if [ "$FULL" -eq 1 ] && [ -d "$DATA_ROOT/$d" ]; then
    mv "$DATA_ROOT/$d" "$DATA_ROOT/$d.old-$STAMP"
    ROLLBACK="$ROLLBACK $d"
  fi
done
[ -d "$DATA_ROOT/app" ] && mv "$DATA_ROOT/app" "$DATA_ROOT/app.old-$STAMP" && ROLLBACK="$ROLLBACK app"
ok "已改名${ROLLBACK:-（无可备份目录）}"

rollback() {
  for d in $ROLLBACK; do
    rm -rf "$DATA_ROOT/$d"
    [ -d "$DATA_ROOT/$d.old-$STAMP" ] && mv "$DATA_ROOT/$d.old-$STAMP" "$DATA_ROOT/$d"
  done
}
trap 'echo "解包失败，正在回滚..."; rollback' ERR

# ---------- 4 解包 ----------
echo "[4/6] 解包"
if [ "$FULL" -eq 1 ] && [ -f "$STAGE/venvs-$STAMP.tar.gz" ]; then
  tar -xzf "$STAGE/venvs-$STAMP.tar.gz" -C "$DATA_ROOT"
  ok "虚拟环境已恢复"
fi
if [ -f "$STAGE/appdata-$STAMP.tar.gz" ]; then
  tar -xzf "$STAGE/appdata-$STAMP.tar.gz" -C "$DATA_ROOT"
  ok "代码与上传文件已恢复"
else
  # 没有 appdata 包时至少把代码拉回来（仓库随时可 clone）
  echo "  ! 没有 appdata 包含代码，请手动 git clone 到 $DATA_ROOT/app"
fi
if [ "$FULL" -eq 1 ] && [ -f "$STAGE/custom-$STAMP.tar.gz" ]; then
  tar -xzf "$STAGE/custom-$STAMP.tar.gz" -C "$DATA_ROOT"
  ok "微调产物已恢复"
fi
if [ "$FULL" -eq 1 ] && [ -f "$STAGE/models-$STAMP.tar.gz" ]; then
  mkdir -p "$DATA_ROOT/models"
  tar -xzf "$STAGE/models-$STAMP.tar.gz" -C "$DATA_ROOT"
  ok "备份内的模型已恢复"
fi

# 公开基座模型若缺失，重新下载（约 7 分钟）
if [ "$FULL" -eq 1 ] && [ ! -f "$DATA_ROOT/models/qwen2.5-7b-instruct/config.json" ]; then
  echo "  ↓ 本地缺少基座模型，从 ModelScope 下载（约 7 分钟）"
  VENV_DIR="$DATA_ROOT/venvs" MODEL_DIR="$DATA_ROOT/models" bash "$REPO_ROOT/scripts/fetch_models.sh"
fi

# ---------- 5 恢复数据库 ----------
echo "[5/6] 恢复数据库"
service mysql start >/dev/null 2>&1 || mysqld_safe >/dev/null 2>&1 &
for _ in $(seq 1 30); do mysqladmin ping >/dev/null 2>&1 && break; sleep 1; done
mysqladmin ping >/dev/null 2>&1 || die "MySQL 没起来"

ENV_FILE="$DATA_ROOT/app/backend/.env"
if [ -f "$ENV_FILE" ]; then
  U="$(grep -E '^MYSQL_USER=' "$ENV_FILE" | cut -d= -f2-)"
  P="$(grep -E '^MYSQL_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)"
  DB="$(grep -E '^MYSQL_DB=' "$ENV_FILE" | cut -d= -f2-)"
  mysql -h127.0.0.1 -u"$U" -p"$P" -e "CREATE DATABASE IF NOT EXISTS \`$DB\` DEFAULT CHARSET utf8mb4;" 2>/dev/null
  gunzip -c "$STAGE/db-$STAMP.sql.gz" | mysql -h127.0.0.1 -u"$U" -p"$P" "$DB" 2>/dev/null
  ok "数据库已恢复"
else
  echo "  ! 没有 .env，跳过数据库恢复（请手动配置后运行 migrate）"
fi

trap - ERR

# ---------- 6 启动 ----------
echo "[6/6] 启动"
bash "$REPO_ROOT/scripts/start.sh" || echo "  ! 启动脚本报告异常，查看 $DATA_ROOT/logs"
sleep 3
curl -fsS http://127.0.0.1:8080/readyz && echo && ok "恢复完成" || echo "  ! readyz 未全绿，检查日志"

echo
echo "旧目录保留在 $DATA_ROOT/*.old-$STAMP，确认无误后可删除："
echo "  rm -rf $DATA_ROOT/*.old-$STAMP"
