#!/bin/bash
# ============================================
# CC-Switch 配置安装脚本
# ============================================
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== 安装 CC-Switch 配置 ==="

mkdir -p ~/.cc-switch
cp "$SCRIPT_DIR/settings.json" ~/.cc-switch/settings.json

if [ ! -f ~/.cc-switch/cc-switch.db ]; then
    cp "$SCRIPT_DIR/cc-switch.db" ~/.cc-switch/cc-switch.db
    echo "✓ 数据库已恢复 (首次安装)"
else
    echo "⚠ ~/.cc-switch/cc-switch.db 已存在，跳过恢复"
fi

echo "✓ 配置文件已复制到 ~/.cc-switch/"
echo "=== 安装完成 ==="
