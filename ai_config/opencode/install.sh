#!/bin/bash
# ============================================
# OpenCode 配置安装脚本
# 用法: install.sh [profile]
#   profile 为空时默认使用 mini 的 key
# ============================================
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROFILE="${1:-mini}"

# 从 master install.sh 继承环境变量，否则自行加载
if [ -z "$MINIEYE_API_KEY" ]; then
    source "$SCRIPT_DIR/../keys/$PROFILE.env"
fi

echo "=== 安装 OpenCode 配置 ($USERNAME) ==="

mkdir -p ~/.config/opencode

# 替换占位符并写入
sed -e "s/__MINIEYE_API_KEY__/$MINIEYE_API_KEY/g" \
    -e "s/__CLAUDE_API_KEY__/$CLAUDE_API_KEY/g" \
    -e "s/__USERNAME__/$USERNAME/g" \
    "$SCRIPT_DIR/opencode.json" > ~/.config/opencode/opencode.json

cp "$SCRIPT_DIR/oh-my-opencode-slim.jsonc" ~/.config/opencode/oh-my-opencode-slim.jsonc
cp "$SCRIPT_DIR/tui.json" ~/.config/opencode/tui.json
cp "$SCRIPT_DIR/tui-preferences.jsonc" ~/.config/opencode/tui-preferences.jsonc

echo "✓ 配置文件已复制到 ~/.config/opencode/ (用户: $USERNAME)"
echo "=== 安装完成 ==="
