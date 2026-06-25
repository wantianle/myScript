#!/bin/bash
# ============================================
# Codex CLI 配置安装脚本
# 用法: install.sh [profile]
# ============================================
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/../install_utils.sh"
PROFILE="${1:-mini}"

if [ -z "$OPENAI_API_KEY" ]; then
    source "$SCRIPT_DIR/../keys/$PROFILE.env"
fi

echo "=== 安装 Codex CLI 配置 ==="

mkdir -p ~/.codex/rules ~/.codex/memories

safe_copy "$SCRIPT_DIR/config.toml" ~/.codex/config.toml "codex/config.toml"
safe_sed_write "$SCRIPT_DIR/auth.json" ~/.codex/auth.json -e "s/__OPENAI_API_KEY__/$OPENAI_API_KEY/g" -- "codex/auth.json"
safe_copy "$SCRIPT_DIR/rules/default.rules" ~/.codex/rules/default.rules "codex/rules/default.rules"
safe_copy "$SCRIPT_DIR/memories/principles.md" ~/.codex/memories/principles.md "codex/memories/principles.md"

echo "✓ 配置文件已复制到 ~/.codex/"
echo "=== 安装完成 ==="
