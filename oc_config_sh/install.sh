#!/bin/bash
# ============================================
# OpenCode 配置安装脚本 - 用户 01297
# ============================================
set -e

echo "=== 安装 OpenCode 配置 ==="

# 1. 创建 opencode 配置目录
mkdir -p ~/.config/opencode

# 2. 复制配置文件
cp "$(dirname "$0")/opencode.json" ~/.config/opencode/opencode.json
cp "$(dirname "$0")/oh-my-opencode-slim.json" ~/.config/opencode/oh-my-opencode-slim.json
cp "$(dirname "$0")/tui.json" ~/.config/opencode/tui.json

echo "✓ 配置文件已复制到 ~/.config/opencode/"

# 3. 追加环境变量到 .zshrc / .bashrc
ENV_BLOCK='
# ai-forge: Intranet 访问凭证
export INTRANET_ACCESS_KEY_ID="01297"
export INTRANET_ACCESS_KEY_SECRET="ea72e973968ac5c0ea27e17d0b3c5776"
export ANTHROPIC_AUTH_TOKEN="sk-4b0a42c7cc3618e03aad34f5206d08c067e10eae9e07b2f689530861203e5da1"
export ANTHROPIC_BASE_URL="https://sub2api.minieye.tech"
'

if [ -f ~/.zshrc ]; then
    if ! grep -q "INTRANET_ACCESS_KEY_ID" ~/.zshrc 2>/dev/null; then
        echo "$ENV_BLOCK" >> ~/.zshrc
        echo "✓ 环境变量已追加到 ~/.zshrc"
    else
        echo "⚠ ~/.zshrc 中已存在 INTRANET_ACCESS_KEY_ID，跳过"
    fi
fi

if [ -f ~/.bashrc ]; then
    if ! grep -q "INTRANET_ACCESS_KEY_ID" ~/.bashrc 2>/dev/null; then
        echo "$ENV_BLOCK" >> ~/.bashrc
        echo "✓ 环境变量已追加到 ~/.bashrc"
    else
        echo "⚠ ~/.bashrc 中已存在 INTRANET_ACCESS_KEY_ID，跳过"
    fi
fi

echo ""
echo "=== 安装完成 ==="
echo "请执行以下命令使环境变量生效:"
echo "  source ~/.zshrc   # 如果使用 zsh"
echo "  source ~/.bashrc  # 如果使用 bash"
