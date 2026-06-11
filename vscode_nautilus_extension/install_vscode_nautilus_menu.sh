#!/usr/bin/env bash

set -euo pipefail

EXT_DIR="${HOME}/.local/share/nautilus-python/extensions"
EXT_FILE="${EXT_DIR}/open_in_vscode.py"
CODE_BIN=""

need_cmd() {
    command -v "$1" >/dev/null 2>&1
}

run_as_root() {
    if [[ "${EUID}" -eq 0 ]]; then
        "$@"
    elif need_cmd sudo; then
        sudo "$@"
    else
        su -c "$(printf '%q ' "$@")"
    fi
}

install_packages() {
    local packages=("$@")
    echo "安装依赖: ${packages[*]}"
    run_as_root apt-get update
    DEBIAN_FRONTEND=noninteractive run_as_root apt-get install -y "${packages[@]}"
}

find_code_bin() {
    local candidate
    for candidate in code code-insiders codium; do
        if need_cmd "${candidate}"; then
            command -v "${candidate}"
            return 0
        fi
    done
    return 1
}

CODE_BIN="$(find_code_bin || true)"

if [[ -z "${CODE_BIN}" ]]; then
    echo "未找到 VS Code 命令行程序。请先确认 'code' 或 'code-insiders' 或 'codium' 已安装并在 PATH 中。"
    exit 1
fi

if ! need_cmd python3; then
    install_packages python3
fi

if ! dpkg -s python3-gi >/dev/null 2>&1; then
    install_packages python3-gi
fi

if ! dpkg -s python3-nautilus >/dev/null 2>&1; then
    install_packages python3-nautilus
fi

if ! python3 -c 'import gi' >/dev/null 2>&1; then
    echo "python3-gi 安装后仍不可用，请检查系统 Python 环境。"
    exit 1
fi

if ! need_cmd nautilus; then
    echo "未检测到 Nautilus。这个脚本只适用于 Ubuntu GNOME 的文件管理器。"
    exit 1
fi

mkdir -p "${EXT_DIR}"

cat > "${EXT_FILE}" <<PYEOF
from gi import require_version
require_version("Nautilus", "4.0")
from gi.repository import GObject, Nautilus
import os
import subprocess
import urllib.parse


CODE_BIN = r"${CODE_BIN}"
MENU_NAME = "OpenInVSCodeExtension"


def uri_to_path(uri: str) -> str:
    parsed = urllib.parse.urlparse(uri)
    return urllib.parse.unquote(parsed.path)


def launch_code(path: str) -> None:
    subprocess.Popen([CODE_BIN, path], start_new_session=True)


class OpenInVSCodeExtension(GObject.GObject, Nautilus.MenuProvider):
    def _make_item(self, title: str, path: str):
        item = Nautilus.MenuItem(
            name=f"{MENU_NAME}::{title}",
            label=title,
            tip=f"Use VS Code to open {path}",
        )
        item.connect("activate", lambda _menu, target=path: launch_code(target))
        return item

    def get_background_items(self, *args):
        current_folder = args[-1]
        path = uri_to_path(current_folder.get_uri())
        if not os.path.isdir(path):
            return []
        return [self._make_item("用 VS Code 打开当前目录", path)]

    def get_file_items(self, *args):
        files = args[-1]
        if len(files) != 1:
            return []
        file_info = files[0]
        if not file_info.is_directory():
            return []
        path = uri_to_path(file_info.get_uri())
        if not os.path.isdir(path):
            return []
        return [self._make_item("用 VS Code 打开", path)]
PYEOF

chmod 0644 "${EXT_FILE}"

nautilus -q >/dev/null 2>&1 || true
sleep 1
nohup nautilus >/dev/null 2>&1 &

cat <<EOF
安装完成：
1. 文件夹右键会出现“用 VS Code 打开”
2. 目录空白处右键会出现“用 VS Code 打开当前目录”

扩展文件：
${EXT_FILE}
EOF
