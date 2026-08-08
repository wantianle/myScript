#!/bin/bash
# ============================================
# Magic Context 配置安装脚本
#
# magic-context.jsonc 由 Magic Context 单独维护；此脚本只安全复制
# 已备份的配置，不生成或复制任何凭证。
# ============================================
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/../install_utils.sh"

echo "=== 安装 Magic Context 配置 ==="

mkdir -p ~/.config/cortexkit

safe_copy "$SCRIPT_DIR/magic-context.jsonc" \
    ~/.config/cortexkit/magic-context.jsonc \
    "cortexkit/magic-context.jsonc"

echo "=== 安装完成 ==="
