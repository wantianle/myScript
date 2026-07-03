#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="mini@192.168.16.40"

usage() {
    cat <<'USAGE'
用法: sync_ai_config.sh <pull|push>

  pull   从远端 (mini@192.168.16.40) 拉取配置到本地
  push   将本地配置推送到远端 (mini@192.168.16.40)

同步内容:
  ~/.config/opencode/
  ~/.cc-switch/cc-switch.db
  ~/.cc-switch/settings.json
USAGE
    exit 1
}

do_sync() {
    local direction="$1"
    local host="$2"

    local src dst err=0

    if [ "$direction" = "pull" ]; then
        # 确保本地目录
        mkdir -p "$HOME/.claude" "$HOME/.codex" "$HOME/.config/opencode" "$HOME/.cc-switch" "$HOME/.ai-forge"
    else
        # 确保远端目录
        ssh "$host" "mkdir -p ~/.claude ~/.codex ~/.config/opencode ~/.cc-switch ~/.ai-forge"
    fi

    transfer() {
        local rel="$1"
        if [ "$direction" = "pull" ]; then
            src="${host}:~/${rel}"
            dst="$HOME/${rel%/*}/"
        else
            src="$HOME/${rel}"
            dst="${host}:~/${rel%/*}/"
        fi
        echo "  ${rel}"
        rsync -av "$src" "$dst" 2>/dev/null || { echo "    [跳过] 文件不存在"; err=$((err+1)); }
    }

    # 单个文件
    for f in \
        ".cc-switch/cc-switch.db" \
        ".cc-switch/settings.json" 
    do
        transfer "$f"
    done

    echo "  .config/opencode/"
    if [ "$direction" = "pull" ]; then
        rsync -av --exclude='node_modules' "${host}:~/.config/opencode/" "$HOME/.config/opencode/" || { echo "    [失败]"; err=$((err+1)); }
    else
        rsync -av --exclude='node_modules' "$HOME/.config/opencode/" "${host}:~/.config/opencode/" || { echo "    [失败]"; err=$((err+1)); }
    fi

    if [ $err -gt 0 ]; then
        echo ""
        echo "⚠  有 ${err} 项跳过（文件不存在），其他已同步完成。"
    fi
}

[ $# -eq 1 ] || usage

case "$1" in
    pull) do_sync "pull" "$REMOTE_HOST" ;;
    push) do_sync "push" "$REMOTE_HOST" ;;
    *)    usage ;;
esac

echo ""
echo "✓ sync $1 完成"
