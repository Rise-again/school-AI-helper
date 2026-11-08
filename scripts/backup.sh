#!/usr/bin/env bash
# 备份到恒源云「个人数据」（/hy-tmp 关机 24 小时会被清空，必须备份到这里）
#
#   bash scripts/backup.sh --full    # 首次 / 环境变更后：venv + 代码 + 数据 + 自训模型
#   bash scripts/backup.sh           # 日常：只备数据库、上传文件、.env（几 MB，可每天跑）
#   bash scripts/backup.sh --full --with-models   # 连公开基座模型一起传（约 18G，一般不必）
#   bash scripts/backup.sh --prune   # 清理远端旧备份，只留最近 5 份
#
# 为什么不默认备模型：Qwen2.5-7B 与两个 bge 都能从 ModelScope 重新下载（约 7 分钟），
# 传 18G 反而更慢。但 models/adapters 下的微调产物无法重下，永远会备。
#
# 前提：先在本机执行一次 `oss login`。
# bucket 自动取 `oss ls` 的第一个；也可用 OSS_BUCKET=oss://xxx 指定。

set -euo pipefail

DATA_ROOT="${DATA_ROOT:-/hy-tmp/campus}"
BACKUP_DIR="$DATA_ROOT/backup"
STAMP="$(date +%F-%H%M)"
MODE="daily"
PRUNE=0
WITH_MODELS=0

for arg in "$@"; do
  case "$arg" in
    --full)  MODE="full" ;;
    --with-models) WITH_MODELS=1 ;;
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

# 恒源云「个人数据」没有 bucket 名，oss:// 就是根；这里统一放到 campus/ 前缀下
OSS_ROOT="${OSS_ROOT:-oss://campus}"
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
  # 必须走 TCP（授权是 campus@127.0.0.1）；--no-tablespaces 避免要求 PROCESS 权限
  if ! mysqldump --single-transaction --quick --no-tablespaces \
       -h127.0.0.1 -u"$user" -p"$pass" "$db" 2>"$BACKUP_DIR/dump.err" | gzip > "$out"; then
    echo "  ✗ 数据库导出失败：$(head -2 "$BACKUP_DIR/dump.err" | tr '\n' ' ')"
    rm -f "$out"
    return 0
  fi
  [ "$(stat -c%s "$out")" -lt 1000 ] && { echo "  ✗ 导出文件异常小（$out）"; rm -f "$out"; return 0; }
  ok "数据库 $(du -h "$out" | cut -f1)"
  echo "$out"
}

# ---------- 小件：代码 + 上传文件 ----------
pack_small() {
  local out="$BACKUP_DIR/appdata-$STAMP.tar.gz"
  # app 里含代码与 .env；data 里含上传文件与向量库（同在 $DATA_ROOT 下，是兄弟目录）
  tar czf "$out" -C "$DATA_ROOT" \
      --exclude='app/backend/.venv' --exclude='app/.git' \
      app data
  ok "代码与上传文件 $(du -h "$out" | cut -f1)"
  echo "$out"
}

# ---------- 自训产物（无法从网上下回来的东西） ----------
pack_custom() {
  local paths=()
  [ -d "$DATA_ROOT/models/adapters" ] && paths+=("models/adapters")
  [ -d "$DATA_ROOT/data/training" ]   && paths+=("data/training")
  [ -d "$DATA_ROOT/data/sft" ]        && paths+=("data/sft")
  if [ "${#paths[@]}" -eq 0 ]; then
    echo "  · 暂无微调产物（models/adapters、data/training、data/sft 都不存在）"
    echo ""
    return 0
  fi
  local out="$BACKUP_DIR/custom-$STAMP.tar.gz"
  tar czf "$out" -C "$DATA_ROOT" "${paths[@]}"
  ok "微调产物 $(du -h "$out" | cut -f1)"
  echo "$out"
}

# ---------- 大件：虚拟环境 ----------
pack_venvs() {
  local out="$BACKUP_DIR/venvs-$STAMP.tar.gz"
  echo "  打包 venvs（13G，约 5–10 分钟）..."
  tar -I 'gzip -1' -cf "$out" -C "$DATA_ROOT" venvs
  ok "虚拟环境 $(du -h "$out" | cut -f1)"
  echo "$out"
}

upload() {
  local file="$1"
  [ -f "$file" ] || return 0
  echo "  ↑ $(basename "$file")"
  oss cp "$file" "$OSS_ROOT/$(basename "$file")" >/dev/null
  ok "已上传 $(basename "$file")"
}

# ---------- 主流程 ----------
if [ "$MODE" = "full" ]; then
  DB="$(dump_db | tail -1)"
  SMALL="$(pack_small | tail -1)"
  VENV="$(pack_venvs | tail -1)"
  CUSTOM="$(pack_custom | tail -1)"
  upload "$DB"; upload "$SMALL"; upload "$VENV"
  [ -n "$CUSTOM" ] && upload "$CUSTOM"

  if [ "$WITH_MODELS" -eq 1 ]; then
    echo "  打包并上传公开基座模型（18G，oss 只收压缩包，约 10 分钟）..."
    tar -I "gzip -1" -cf "$BACKUP_DIR/models-$STAMP.tar.gz" -C "$DATA_ROOT" models
    upload "$BACKUP_DIR/models-$STAMP.tar.gz"
    ok "模型已上传"
    MODELS_NOTE="included"
  else
    echo "  · 跳过公开模型（可用 scripts/fetch_models.sh 重新下载）"
    MODELS_NOTE="public-skip"
  fi

  cat > "$BACKUP_DIR/manifest-$STAMP.txt" <<EOF
backup=$STAMP
mode=full
db=$(basename "${DB:-none}")
appdata=$(basename "${SMALL:-none}")
venvs=$(basename "${VENV:-none}")
custom=$(basename "${CUSTOM:-none}")
models=$MODELS_NOTE
EOF
  upload "$BACKUP_DIR/manifest-$STAMP.txt"
else
  DB="$(dump_db | tail -1)"
  SMALL="$(pack_small | tail -1)"
  upload "$DB"; upload "$SMALL"
fi

# 本地只留最近 3 份，别把数据盘塞满
# 本地只留最近几份（通配符没匹配到时不要让 set -e 中止脚本）
prune_local() {
  local pattern="$1" keep="$2"
  ls -1t $pattern 2>/dev/null | tail -n +$((keep + 1)) | xargs -r rm -f || true
}
prune_local "$BACKUP_DIR"/db-*.sql.gz 3
prune_local "$BACKUP_DIR"/appdata-*.tar.gz 3
prune_local "$BACKUP_DIR"/custom-*.tar.gz 3
prune_local "$BACKUP_DIR"/venvs-*.tar.gz 2
prune_local "$BACKUP_DIR"/models-*.tar.gz 1

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
