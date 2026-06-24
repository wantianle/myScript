#!/bin/bash
# ============================================
# AI 工具配置 一键安装
# 用法: install.sh [profile]
#   profile 为空时默认 mini
#   可选: mini | 01297
# 示例:
#   bash install.sh          # 用 mini 的 key
#   bash install.sh 01297    # 用 01297 的 key
# ============================================
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROFILE="${1:-mini}"

if [ ! -f "$SCRIPT_DIR/keys/$PROFILE.env" ]; then
    echo "[ERROR] 未知的 profile: $PROFILE"
    echo "  可用: $(ls "$SCRIPT_DIR/keys"/*.env | xargs -n1 basename | sed 's/.env//' | tr '\n' ' ')"
    exit 1
fi

echo "============================================"
echo "  AI 工具配置 一键部署"
echo "  用户: $PROFILE"
echo "============================================"
echo ""

# 加载密钥并导出给子脚本
source "$SCRIPT_DIR/keys/$PROFILE.env"
export MINIEYE_API_KEY CLAUDE_API_KEY OPENAI_API_KEY
export ANTHROPIC_BASE_URL INTRANET_ACCESS_KEY_ID INTRANET_ACCESS_KEY_SECRET
export USERNAME

for tool in opencode codex claude cc-switch; do
    if [ -f "$SCRIPT_DIR/$tool/install.sh" ]; then
        echo ">>> [$tool] 配置..."
        bash "$SCRIPT_DIR/$tool/install.sh"
        echo ""
    fi
done

# 写入 shell 环境变量
ENV_BLOCK="
# ai-forge: Intranet 访问凭证 ($PROFILE)
export INTRANET_ACCESS_KEY_ID=\"$INTRANET_ACCESS_KEY_ID\"
export INTRANET_ACCESS_KEY_SECRET=\"$INTRANET_ACCESS_KEY_SECRET\"
export ANTHROPIC_AUTH_TOKEN=\"$CLAUDE_API_KEY\"
export ANTHROPIC_BASE_URL=\"$ANTHROPIC_BASE_URL\"
"

if [ -f ~/.zshrc ]; then
    if ! grep -q "INTRANET_ACCESS_KEY_ID" ~/.zshrc 2>/dev/null; then
        echo "$ENV_BLOCK" >> ~/.zshrc
        echo "✓ 环境变量已追加到 ~/.zshrc"
    else
        echo "⚠ ~/.zshrc 中已存在 INTRANET_ACCESS_KEY_ID，跳过写入"
    fi
fi

echo "============================================"
echo "  全部安装完成!"
echo "  请执行: source ~/.zshrc"
echo "============================================"
