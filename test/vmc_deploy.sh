#! /usr/bin/env bash
# https://alidocs.dingtalk.com/i/nodes/R1zknDm0WR363nr5TggmKjLOVBQEx5rG

set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../" && pwd -P)"
CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

source "${ROOT_DIR}/common.sh"

# 判断架构
ARCH_TYPE=$(uname -m)
case $ARCH_TYPE in
    x86_64) ARCH_VAR="amd64" ;;
    aarch64) ARCH_VAR="arm64" ;;
    armv7l) ARCH_VAR="arm32" ;;
    *) ARCH_VAR="unknown" ;;
esac

if [ "$ARCH_VAR" != "amd64" ]; then
    error "当前系统的CPU架构类型为:$ARCH_VAR, 请确认是否在个人PC电脑端!"
    exit 1
fi

# 配置 VMC 安装路径
VMC_BIN_DIR="$HOME/.vmc/bin"
VMC_EXEC="$VMC_BIN_DIR/vmc"
SRC_VMC="$CURR_DIR/vmc/vmc_linux_amd64_0.0.151"

info "正在安装 vmc 到 $VMC_BIN_DIR ..."

if [ ! -f "$SRC_VMC" ]; then
    error "源文件不存在: $SRC_VMC"
    exit 1
fi

mkdir -p "$VMC_BIN_DIR"
cp "$SRC_VMC" "$VMC_EXEC"

# 执行权限
chmod 755 "$VMC_EXEC"

# 临时将 vmc 加入当前 PATH，确保脚本后续能调用 vmc 命令
export PATH="$VMC_BIN_DIR:$PATH"

# 配置 Shell 环境 (Bash 和 Zsh 分别配置)
add_path_to_rc() {
    local rc_file=$1
    local bin_path=$2
    if [ -f "$rc_file" ]; then
        if ! grep -q "$bin_path" "$rc_file"; then
            info "添加 PATH 到 $rc_file"
            echo 'export PATH="'"$bin_path"':$PATH"' >> "$rc_file"
        fi
    fi
}

# 配置 Bash
if [ -f "$HOME/.bashrc" ]; then
    add_path_to_rc "$HOME/.bashrc" "$VMC_BIN_DIR"

    # 配置 Bash 自动补全
    COMPLETION_DIR="$HOME/.vmc/completions"
    mkdir -p "$COMPLETION_DIR"

    # 生成补全脚本
    if "$VMC_EXEC" completion bash > "$COMPLETION_DIR/vmc.bash"; then
        # 在 .bashrc 中引用
        if ! grep -q "$COMPLETION_DIR/vmc.bash" "$HOME/.bashrc"; then
            echo "source $COMPLETION_DIR/vmc.bash" >> "$HOME/.bashrc"
        fi
    fi
fi

# 配置 Zsh
if [ -f "$HOME/.zshrc" ] || command -v zsh >/dev/null 2>&1; then
    # 即使当前不在 zsh 下，如果用户有 .zshrc 也帮他配好
    ZSHRC="$HOME/.zshrc"
    [ ! -f "$ZSHRC" ] && touch "$ZSHRC"

    add_path_to_rc "$ZSHRC" "$VMC_BIN_DIR"

    # 配置 Zsh 自动补全
    ZSH_COMP_DIR="$HOME/.vmc/zsh_completions"
    mkdir -p "$ZSH_COMP_DIR"

    # 生成补全文件 _vmc
    "$VMC_EXEC" completion zsh > "$ZSH_COMP_DIR/_vmc"

    # 将补全目录加入 fpath
    if ! grep -q "$ZSH_COMP_DIR" "$ZSHRC"; then
        info "添加 Zsh 补全路径到 $ZSHRC"
        echo 'fpath=('"$ZSH_COMP_DIR"' $fpath)' >> "$ZSHRC"
        echo "autoload -U compinit; compinit" >> "$ZSHRC"
    fi
fi

# 登录与更新
info "正在配置 Token 并更新..."
"$VMC_EXEC" config --token "adtestgroup01|XX8OXPUmI4mkPsSkBLZNWA4EawDbtsNCjn0UOdW5peY6qozEGO7WbIfmK1DwTE5L|G4E7EVWW5WH3YYMQ4TY2XRNHXDEDPPTN"
"$VMC_EXEC" self update

# 配置 vmc.sh
PROJECT_DIR="$HOME/project"
TARGET_SCRIPT="$PROJECT_DIR/vmc.sh"
SOURCE_SCRIPT="$CURR_DIR/vmc.sh_for_tester"

if [ -f "$SOURCE_SCRIPT" ]; then
    mkdir -p "$PROJECT_DIR"
    if [ -f "$TARGET_SCRIPT" ]; then
        warning "文件已存在: $TARGET_SCRIPT，将被覆盖。"
    fi
    cp "$SOURCE_SCRIPT" "$TARGET_SCRIPT"
    chmod +x "$TARGET_SCRIPT"
else
    warning "未找到 vmc.sh_for_tester，跳过项目脚本复制。"
fi

info "部署完成!"
warning "========================================================"
warning "请执行以下命令使环境变量立即生效："
if [[ "$SHELL" == *"zsh"* ]]; then
    warning "  source ~/.zshrc"
else
    warning "  source ~/.bashrc"
fi
warning "========================================================"
