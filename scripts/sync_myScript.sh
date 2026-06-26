#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="mini@192.168.16.40"
SRC_DIR="$HOME/dev/myScript"

usage() {
    cat <<'USAGE'
用法: sync_myScript.sh <pull|push>

  pull   从远端 (mini@192.168.16.40) 拉取 ~/dev/myScript 到本地
  push   将本地 ~/dev/myScript 推送到远端 (mini@192.168.16.40)

排除项:
  __pycache__/  .venv/  node_modules/  .git/
USAGE
    exit 1
}

[ $# -eq 1 ] || usage

case "$1" in
    pull)
        echo "→ 从 ${REMOTE_HOST} 拉取 ~/dev/myScript ..."
        mkdir -p "$SRC_DIR"
        rsync -av \
            --exclude='__pycache__/' \
            --exclude='.venv/' \
            --exclude='node_modules/' \
            --exclude='.git/' \
            "${REMOTE_HOST}:~/dev/myScript/" \
            "$SRC_DIR/"
        ;;
    push)
        echo "→ 推送 ~/dev/myScript 到 ${REMOTE_HOST} ..."
        ssh "$REMOTE_HOST" "mkdir -p ~/dev/myScript"
        rsync -av \
            --exclude='__pycache__/' \
            --exclude='.venv/' \
            --exclude='node_modules/' \
            --exclude='.git/' \
            "$SRC_DIR/" \
            "${REMOTE_HOST}:~/dev/myScript/"
        ;;
    *)
        usage
        ;;
esac

echo ""
echo "✓ sync $1 完成"
