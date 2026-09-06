#!/bin/bash
# ============================================
# OpenCode 配置安装脚本
# 用法: install.sh [profile]
#   profile 为空时默认使用 mini 的 key
# ============================================
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/../install_utils.sh"
PROFILE="${1:-mini}"

# 从 master install.sh 继承环境变量，否则自行加载
if [ -z "$MINIEYE_API_KEY" ]; then
    source "$SCRIPT_DIR/../keys/$PROFILE.env"
fi

echo "=== 安装 OpenCode 配置 ($USERNAME) ==="

mkdir -p ~/.config/opencode

# 直接复制本机同步来的 opencode.jsonc（含真实配置）
safe_copy "$SCRIPT_DIR/opencode.jsonc" ~/.config/opencode/opencode.jsonc "opencode/opencode.jsonc"

safe_copy "$SCRIPT_DIR/oh-my-opencode-slim.jsonc" ~/.config/opencode/oh-my-opencode-slim.jsonc "opencode/oh-my-opencode-slim.jsonc"
safe_copy "$SCRIPT_DIR/tui.json" ~/.config/opencode/tui.json "opencode/tui.json"
safe_copy "$SCRIPT_DIR/tui-preferences.jsonc" ~/.config/opencode/tui-preferences.jsonc "opencode/tui-preferences.jsonc"

echo "✓ 配置文件已复制到 ~/.config/opencode/ (用户: $USERNAME)"
echo "=== 安装完成 ==="
