#!/usr/bin/env bash

set -euo pipefail

EXT_FILE="${HOME}/.local/share/nautilus-python/extensions/open_in_vscode.py"

if [[ -f "${EXT_FILE}" ]]; then
    rm -f "${EXT_FILE}"
    echo "已删除扩展：${EXT_FILE}"
else
    echo "未找到扩展：${EXT_FILE}"
fi

nautilus -q >/dev/null 2>&1 || true
sleep 1
nohup nautilus >/dev/null 2>&1 &

echo "卸载完成。重新打开文件管理器后右键菜单会消失。"
