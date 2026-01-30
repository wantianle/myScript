#!/bin/bash

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/utils.sh"
[[ "$(uname -m)" != "x86_64" ]] && { log_error "仅支持 x86_64 架构!"; exit 1; }
VMC_BIN_DIR="$HOME/.vmc/bin"
VMC_EXEC="$VMC_BIN_DIR/vmc"
SRC_VMC="$DIR/../bin/vmc_linux_amd64_0.0.151"
MDRIVE_ROOT="$HOME/project"

log_info "正在安装 vmc 到 $VMC_BIN_DIR ..."
mkdir -p "$VMC_BIN_DIR"
cp "$SRC_VMC" "$VMC_EXEC"
chmod 755 "$VMC_EXEC"

setup_shell_env() {
    local shell_name=$1
    local rc_file=$2
    if ! grep -q "$VMC_BIN_DIR" "$rc_file"; then
        echo "export PATH=\"$VMC_BIN_DIR:\$PATH\"" >> "$rc_file"
    fi
    if [[ "$shell_name" == "zsh" ]]; then
        local zsh_comp="$HOME/.vmc/zsh_completions"
        mkdir -p "$zsh_comp"
        "$VMC_EXEC" completion zsh > "$zsh_comp/_vmc"
        grep -q "$zsh_comp" "$rc_file" || {
            echo "fpath=($zsh_comp \$fpath)"
            echo "autoload -U compinit; compinit"
        } >> "$rc_file"
    else
        local bash_comp="$HOME/.vmc/completions/vmc.bash"
        mkdir -p "$(dirname "$bash_comp")"
        "$VMC_EXEC" completion bash > "$bash_comp"
        grep -q "$bash_comp" "$rc_file" || echo "source $bash_comp" >> "$rc_file"
    fi
}

export PATH="$VMC_BIN_DIR:$PATH"

[[ -f "$HOME/.bashrc" ]] && setup_shell_env "bash" "$HOME/.bashrc"
[[ -f "$HOME/.zshrc" ]]  && setup_shell_env "zsh" "$HOME/.zshrc"

log_info "配置 Token 并更新..."
"$VMC_EXEC" config --token "adtestgroup01|XX8OXPUmI4mkPsSkBLZNWA4EawDbtsNCjn0UOdW5peY6qozEGO7WbIfmK1DwTE5L|G4E7EVWW5WH3YYMQ4TY2XRNHXDEDPPTN"
"$VMC_EXEC" self update

mkdir -p "$MDRIVE_ROOT"
cp "$DIR/vmc.sh" "$MDRIVE_ROOT/vmc.sh"
chmod +x "$MDRIVE_ROOT/vmc.sh"

log_info "部署完成! 请运行 'source ~/.zshrc' 和 'source ~/.bashrc' 使补全生效。"
