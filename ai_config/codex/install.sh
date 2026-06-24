#!/bin/bash
# ============================================
# Codex CLI 配置安装脚本
# 用法: install.sh [profile]
# ============================================
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROFILE="${1:-mini}"

if [ -z "$OPENAI_API_KEY" ]; then
    source "$SCRIPT_DIR/../keys/$PROFILE.env"
fi

echo "=== 安装 Codex CLI 配置 ==="

mkdir -p ~/.codex/rules ~/.codex/memories

cp "$SCRIPT_DIR/config.toml" ~/.codex/config.toml
sed "s/__OPENAI_API_KEY__/$OPENAI_API_KEY/g" \
    "$SCRIPT_DIR/auth.json" > ~/.codex/auth.json
cp "$SCRIPT_DIR/rules/default.rules" ~/.codex/rules/default.rules
cp "$SCRIPT_DIR/memories/principles.md" ~/.codex/memories/principles.md

echo "✓ 配置文件已复制到 ~/.codex/"
echo "=== 安装完成 ==="
