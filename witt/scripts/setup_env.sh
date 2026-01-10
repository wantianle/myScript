#!/usr/bin/env bash

set -Eeuo pipefail
UTILS_DIR="${BASH_SOURCE[0]%/*}/../utils"
source "$UTILS_DIR/utils.sh"
trap 'failure ${LINENO} "$BASH_COMMAND"' ERR

INDEX="https://pypi.tuna.tsinghua.edu.cn/simple"
MDRIVE_ROOT="$HOME/project"
VMC_SH="$MDRIVE_ROOT/vmc.sh"
# 检查并安装 pip
if ! command -v pip3 &> /dev/null; then
    log_warnning "未检测到 pip，尝试安装..."
    sudo apt-get update && sudo apt-get install python3-pip -y || { log_error "pip 安装失败"; exit 1; }
fi

# 检查并安装 Python 依赖
deps=("yaml" "alive-progress")

for pkg in "${deps[@]}"; do
    # 使用 python3 -c 快速检查包是否存在
    if ! python3 -c "import ${pkg//-/_}" &> /dev/null; then
        log_warnning "正在安装缺失 python 依赖: $pkg ..."
        pip3 install "$pkg" -i $INDEX || { log_error "依赖 $pkg 安装失败"; exit 1; }
    fi
done

if ! command -v jq >/dev/null 2>&1; then
    log_warnning "未检测到 jq ，尝试安装..."
    sudo apt-get update && sudo apt-get install -y jq || { log_error "jq 安装失败"; exit 1; }
fi

if ! command -v vmc >/dev/null 2>&1; then
    log_warnning "未检测到 vmc 工具，尝试安装..."
    bash "${BASH_SOURCE[0]%/*}/vmc_deploy.sh"
    source ~/.bashrc
fi

if [[ ! -f $VMC_SH ]]; then
    log_warnning "未找到 vmc.sh 文件, 尝试创建..."
    mkdir -p $MDRIVE_ROOT
    cp "$UTILS_DIR/vmc.sh_for_tester" "$MDRIVE_ROOT/vmc.sh"
    chmod +x "$MDRIVE_ROOT/vmc.sh"
fi

if [[ ! -d "$MDRIVE_ROOT/mdrive" ]]; then
    log_warnning "未检测到 mdrive 环境，尝试安装..."
    export VMC_SOFTWARE=$MDRIVE_ROOT
    install_cmd=$(vmc fsearch -n mdrive -l amd64 -i 1 --verbose | awk -F': ' '/Install/ {print $2}')
    eval ${install_cmd}
fi
