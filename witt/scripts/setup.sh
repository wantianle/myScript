#!/usr/bin/env bash

set -Eeuo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/utils.sh"

INDEX="https://mirrors.aliyun.com/pypi/simple/"
MDRIVE_ROOT="$HOME/project"
VMC_SH="$MDRIVE_ROOT/vmc.sh"
CONTAINER="mdrive_dev_vmc_minieye"
DEV_START_SCRIPT="$MDRIVE_ROOT/mdrive/docker/dev_start.sh"
DATA_ROOT="/media/mini"
VENV_DIR="$DIR/../.venv"
VENV_PIP="$VENV_DIR/bin/pip"
PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')

ensure_venv_support() {
    if python3 -m venv --help >/dev/null 2>&1; then
        return 0
    fi

    log_warning "当前 Python 缺少 venv 模块，尝试安装..."
    if ! sudo apt-get update; then
        log_warning "apt-get update 存在不可用源，继续尝试安装 venv 依赖..."
    fi

    if sudo apt-get install -y "python${PY_VER}-venv"; then
        return 0
    fi

    log_warning "python${PY_VER}-venv 安装失败，尝试回退到 python3-venv..."
    sudo apt-get install -y python3-venv
}

if [ ! -d "$VENV_DIR" ]; then
    log_warning "未检测到虚拟环境，尝试安装..."
    ensure_venv_support
    python3 -m venv "$VENV_DIR"
    "$VENV_PIP" install -i "$INDEX" --trusted-host mirrors.aliyun.com -r "$DIR/../requirements.txt"
fi

source "$VENV_DIR/bin/activate"

if ! command -v jq >/dev/null 2>&1; then
    log_warning "未检测到 jq ，尝试安装..."
    sudo apt-get install -y jq
fi

if ! command -v vmc >/dev/null 2>&1; then
    log_warning "未检测到 vmc 工具，尝试安装..."
    bash "$DIR/vmc_deploy.sh"
fi

if [[ ! -f $VMC_SH ]]; then
    log_warning "未找到 vmc.sh 文件, 尝试创建..."
    mkdir -p "$MDRIVE_ROOT"
    cp "$DIR/vmc.sh" "$VMC_SH"
    chmod +x "$VMC_SH"
fi

if [[ ! -d "$MDRIVE_ROOT/mdrive" ]]; then
    log_warning "未检测到 mdrive 环境，尝试安装..."
    export VMC_SOFTWARE=$MDRIVE_ROOT
    cmd=$(vmc fsearch -n mdrive -l amd64 | awk -F'[,:]' '$2 == " mdrive" {print $4; exit}' | xargs -I {} echo "vmc install -n mdrive -v {}")
    eval "$cmd"
    cp "$DIR/patch.sh" "$MDRIVE_ROOT/patch.sh"
    chmod +x "$MDRIVE_ROOT/patch.sh"
    bash "$MDRIVE_ROOT/patch.sh"
fi

if [[ ! -e "/media" ]]; then
    log_error "/media 目录不存在！"
    exit 1
fi

if [[ ! -O "/media" ]]; then
    log_warning "/media 没有读写权限，尝试更改..."
    sudo chown "$USER:$USER" /media
fi

if [[ ! -e "$DATA_ROOT" ]]; then
    mkdir -p "$DATA_ROOT"
fi

if [[ ! -O "$DATA_ROOT" ]]; then
    log_warning "$DATA_ROOT 没有读写权限，尝试更改..."
    sudo chown -R "$USER:$USER" "$DATA_ROOT"
fi

if [[ -z "$(docker ps -a -q -f name=$CONTAINER)" ]]; then
    log_warning "docker 容器不存在, 尝试创建环境..."
    bash "$DEV_START_SCRIPT"
fi

if ! docker exec "$CONTAINER" /bin/bash -c "source /mdrive/mdrive/setup.sh && cyber_recorder --help" >/dev/null 2>&1; then
    log_error "docker 容器无法正确打开！"
    exit 1
fi

python3 "$DIR/../main.py"
