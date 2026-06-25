#!/bin/bash
# ============================================
# Claude Code 配置安装脚本
# 用法: install.sh [profile]
# ============================================
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/../install_utils.sh"
PROFILE="${1:-mini}"

if [ -z "$CLAUDE_API_KEY" ]; then
    source "$SCRIPT_DIR/../keys/$PROFILE.env"
fi

echo "=== 安装 Claude Code 配置 ==="

mkdir -p ~/.claude

safe_sed_write "$SCRIPT_DIR/settings.json" ~/.claude/settings.json -e "s/__CLAUDE_API_KEY__/$CLAUDE_API_KEY/g" -e "s|__ANTHROPIC_BASE_URL__|$ANTHROPIC_BASE_URL|g" -- "claude/settings.json"

echo "✓ 配置文件已复制到 ~/.claude/"
echo "=== 安装完成 ==="
