#!/bin/bash
# ============================================
# CC-Switch 配置安装脚本
# ============================================
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/../install_utils.sh"

echo "=== 安装 CC-Switch 配置 ==="

mkdir -p ~/.cc-switch
safe_copy "$SCRIPT_DIR/settings.json" ~/.cc-switch/settings.json "cc-switch/settings.json"

safe_copy "$SCRIPT_DIR/cc-switch.db" ~/.cc-switch/cc-switch.db "cc-switch/cc-switch.db"

echo "✓ 配置文件已复制到 ~/.cc-switch/"
echo "=== 安装完成 ==="
