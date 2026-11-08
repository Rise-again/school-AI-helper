#!/usr/bin/env bash
# 备份到恒源云「个人数据」（/hy-tmp 关机 24 小时会被清空，必须备份到这里）
#
#   bash scripts/backup.sh --full    # 首次 / 环境变更后：venv + 模型 + 代码 + 数据库
#   bash scripts/backup.sh           # 日常：只备数据库、上传文件、.env（几 MB，可每天跑）
#   bash scripts/backup.sh --prune   # 清理远端旧备份，只留最近 5 份
#
# 前提：先在本机执行一次 `oss login`。
# bucket 自动取 `oss ls` 的第一个；也可用 OSS_BUCKET=oss://xxx 指定。

set -euo pipefail

DATA_ROOT="${DATA_ROOT:-/hy-tmp/campus}"
BACKUP_DIR="$DATA_ROOT/backup"
STAMP="$(date +%F-%H%M)"
MODE="daily"
PRUNE=0

for arg in "$@"; do
  case "$arg" in
    --full)  MODE="full" ;;
    --prune) PRUNE=1 ;;
    -h|--help) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "未知参数：$arg" >&2; exit 2 ;;
  esac
done

ok()  { printf '  \033[32m✓\033[0m %s\n' "$1"; }
die() { printf '\033[31m✗ %s\033[0m\n' "$1" >&2; exit 1; }

command -v oss >/dev/null || die "缺少 oss 命令（恒源云实例自带）"
if ! oss ls >/dev/null 2>&1; then
  die "oss 未登录。先在服务器上执行：oss login"
fi

OSS_BUCKET="${OSS_BUCKET:-$(oss ls 2>/dev/null | awk '{print $1}' | grep -m1 '^oss://' || true)}"
[ -n "$OSS_BUCKET" ] || die "找不到 bucket，请用 OSS_BUCKET=oss://xxx 指定"
OSS_ROOT="${OSS_BUCKET%/}/campus"
mkdir -p "$BACKUP_DIR"

echo "备份模式：$MODE"
echo "本地目录：$DATA_ROOT"
echo "远端目录：$OSS_ROOT"

# ---------- 数据库 ----------
dump_db() {
  local env_file="$DATA_ROOT/app/backend/.env"
  [ -f "$env_file" ] || { echo "  ! 没有 .env，跳过数据库"; return 0; }
  local user pass db
  user="$(grep -E '^MYSQL_USER=' "$env_file" | cut -d= -f2-)"
  pass="$(grep -E '^MYSQL_PASSWORD=' "$env_file" | cut -d= -f2-)"
  db="$(grep -E '^MYSQL_DB=' "$env_file" | cut -d= -f2-)"
  local out="$BACKUP_DIR/db-$STAMP.sql.gz"
  mysqldump --single-transaction --quick -u"$user" -p"$pass" "$db" 2>/dev/null | gzip > "$out"
  ok "数据库 $(du -h "$out" | cut -f1)"
  echo "$out"
}

# ---------- 小件：代码 + 上传文件 ----------
pack_small() {
  local out="$BACKUP_DIR/appdata-$STAMP.tgz"
  tar czf "$out" -C "$DATA_ROOT" \
      --exclude='app/backend/.venv' --exclude='app/.git' \
      app/data app/backend/.env 2>/dev/null || tar czf "$out" -C "$DATA_ROOT" \
      --exclude='app/backend/.venv' app 2>/dev/null || true
  [ -f "$out" ] && ok "代码与上传文件 $(du -h "$out" | cut -f1)"
  echo "$out"
}

# ---------- 大件：虚拟环境 ----------
pack_venvs() {
  local out="$BACKUP_DIR/venvs-$STAMP.tgz"
  echo "  打包 venvs（13G，约 5–10 分钟）..."
  tar -I 'gzip -1' -cf "$out" -C "$DATA_ROOT" venvs
  ok "虚拟环境 $(du -h "$out" | cut -f1)"
  echo "$out"
}

upload() {
  local file="$1"
  [ -f "$file" ] || return 0
  echo "  ↑ $(basename "$file")"
  oss cp "$file" "$OSS_ROOT/" >/dev/null
  ok "已上传 $(basename "$file")"
}

# ---------- 主流程 ----------
if [ "$MODE" = "full" ]; then
  DB="$(dump_db | tail -1)"
  SMALL="$(pack_small | tail -1)"
  VENV="$(pack_venvs | tail -1)"
  upload "$DB"; upload "$SMALL"; upload "$VENV"

  echo "  上传模型（18G，大文件直传，可断点续传）..."
  oss cp -r "$DATA_ROOT/models" "$OSS_ROOT/" >/dev/null
  ok "模型已上传"

  cat > "$BACKUP_DIR/manifest-$STAMP.txt" <<EOF
backup=$STAMP
mode=full
db=$(basename "${DB:-none}")
appdata=$(basename "${SMALL:-none}")
venvs=$(basename "${VENV:-none}")
models=models/
EOF
  upload "$BACKUP_DIR/manifest-$STAMP.txt"
else
  DB="$(dump_db | tail -1)"
  SMALL="$(pack_small | tail -1)"
  upload "$DB"; upload "$SMALL"
fi

# 本地只留最近 3 份，别把数据盘塞满
ls -1t "$BACKUP_DIR"/db-*.sql.gz 2>/dev/null | tail -n +4 | xargs -r rm -f
ls -1t "$BACKUP_DIR"/appdata-*.tgz 2>/dev/null | tail -n +4 | xargs -r rm -f
ls -1t "$BACKUP_DIR"/venvs-*.tgz 2>/dev/null | tail -n +2 | xargs -r rm -f

if [ "$PRUNE" -eq 1 ]; then
  echo "清理远端旧备份（保留最近 5 份）..."
  for prefix in db- appdata- venvs- manifest-; do
    oss ls "$OSS_ROOT/" 2>/dev/null | grep "$prefix" | sort | head -n -5 | awk '{print $NF}' \
      | while read -r obj; do [ -n "$obj" ] && oss rm "$obj" >/dev/null 2>&1 || true; done
  done
  ok "清理完成"
fi

echo
echo "完成。远端：$OSS_ROOT/"
echo "恢复：bash scripts/restore.sh --from <备份时间戳>"
