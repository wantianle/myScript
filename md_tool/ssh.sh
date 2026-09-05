#!/usr/bin/env bash

USER_NAME="nvidia"
SOC1_IP="192.168.10.2"
SOC2_IP="192.168.10.3"
# WAN_DOMAIN="192.168.16.104"
WAN_DOMAIN="ad.minieye.tech"
KEY_PATH="$HOME/.ssh/id_ed25519"
CONFIG_PATH="$HOME/.ssh/config"

RED='\033[1;31m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
NC='\033[0m'

# 备选密码列表（按顺序尝试）
SSH_PASSWORDS=("mini!@#123.com" "nvidia")
SSH_PASS_CACHED=""

# 避免 ssh 把本机 zh_CN.UTF-8 转发到车端（车端无此 locale 会导致 setlocale 警告）
export LC_ALL=C

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_err()  { echo -e "${RED}[ERROR]${NC} $1"; }

echo -e "${BLUE}===============================================${NC}"
echo -e "  ${GREEN}1)${NC} 局域网免密  (SOC1: ${YELLOW}.10.2${NC}, SOC2: ${YELLOW}.10.3${NC})"
echo -e "  ${GREEN}2)${NC} 公网批量免密 (域名: ${YELLOW}${WAN_DOMAIN}${NC})"
echo -e "${BLUE}===============================================${NC}"
read -rp "  请选择模式 [1/2]: " MODE
echo ""

# [1/3] 密钥生成逻辑
log_info "检查本地密钥..."
mkdir -p "$HOME/.ssh"

chmod 700 "$HOME/.ssh"
if [ ! -f "$KEY_PATH" ]; then
    log_info "  未发现密钥，正在生成 ed25519 密钥对..."
    ssh-keygen -t ed25519 -f "$KEY_PATH" -N "" 2>&1 | while IFS= read -r line; do
        echo "        $line"
    done
    log_ok "  密钥已生成: $KEY_PATH"
else
    log_ok "  密钥已存在: $KEY_PATH"
fi

# 公网模式下，在 SOC1 上配置 SOC 间免密、快捷登录和主机名。
configure_vehicle() {
    local port="$1"
    local target="$USER_NAME@$WAN_DOMAIN"
    local remote_script="/tmp/ssh-configure-${port}-$$.sh"
    local soc1_ip_q soc2_ip_q user_name_q remote_script_q ssh_passwords_q remote_command

    printf -v soc1_ip_q '%q' "$SOC1_IP"
    printf -v soc2_ip_q '%q' "$SOC2_IP"
    printf -v user_name_q '%q' "$USER_NAME"
    printf -v remote_script_q '%q' "$remote_script"
    printf -v ssh_passwords_q '%q ' "${SSH_PASSWORDS[@]}"

    echo ""
    log_info "正在配置端口 $port 对应车辆的 SOC1 <-> SOC2 免密与主机名..."

    # 先通过非 TTY 会话上传脚本，避免脚本内容与后续交互提示共用同一个 PTY。
    # SSH_PASSWORDS 密码表由本地 printf %q 序列化后注入脚本头部，远端脚本不再硬编码密码。
    if ! { printf 'SSH_PASSWORDS=(%s)\n' "${ssh_passwords_q% }"
           cat
         } <<'REMOTE' | ssh -T -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
            -p "$port" "$target" "cat > $remote_script_q"
set -e
set +H

SUDO_PASS_CACHED=""
SOC2_PASS_CACHED=""

sudo_pass_discover() {
    local password
    if [[ -n "$SUDO_PASS_CACHED" ]] && printf '%s\n' "$SUDO_PASS_CACHED" | sudo -S -p '' -v 2>/dev/null; then
        return 0
    fi
    for password in "${SSH_PASSWORDS[@]}"; do
        if printf '%s\n' "$password" | sudo -S -p '' -v 2>/dev/null; then
            SUDO_PASS_CACHED="$password"
            return 0
        fi
    done
    read -rsp "  请输入 SOC1 sudo 密码: " SUDO_PASS_CACHED </dev/tty
    echo ""
    [[ -n "$SUDO_PASS_CACHED" ]] && printf '%s\n' "$SUDO_PASS_CACHED" | sudo -S -p '' -v
}

copy_soc2_key() {
    local password
    local target="$USER_NAME@$SOC2_IP"
    local copy_id=(ssh-copy-id -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -i "$HOME/.ssh/id_ed25519.pub" "$target")

    if ssh -n -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR soc2 exit 2>/dev/null; then
        return 0
    fi

    if command -v sshpass &>/dev/null; then
        if [[ -n "$SOC2_PASS_CACHED" ]] && SSHPASS="$SOC2_PASS_CACHED" sshpass -e "${copy_id[@]}"; then
            return 0
        fi
        SOC2_PASS_CACHED=""

        for password in "${SSH_PASSWORDS[@]}"; do
            if SSHPASS="$password" sshpass -e "${copy_id[@]}"; then
                SOC2_PASS_CACHED="$password"
                return 0
            fi
        done
    fi

    ssh-copy-id -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -i "$HOME/.ssh/id_ed25519.pub" "$target" || return 1
    read -rsp "  请输入 SOC2 密码（用于 sudo）: " SOC2_PASS_CACHED </dev/tty
    echo ""
    [[ -n "$SOC2_PASS_CACHED" ]]
}

soc2_sudo_pass_discover() {
    local password

    if [[ -n "$SOC2_PASS_CACHED" ]] && printf '%s\n' "$SOC2_PASS_CACHED" | ssh -o LogLevel=ERROR soc2 "sudo -S -p '' -v"; then
        return 0
    fi

    for password in "${SSH_PASSWORDS[@]}"; do
        if printf '%s\n' "$password" | ssh -o LogLevel=ERROR soc2 "sudo -S -p '' -v"; then
            SOC2_PASS_CACHED="$password"
            return 0
        fi
    done

    read -rsp "  请输入 SOC2 sudo 密码: " SOC2_PASS_CACHED </dev/tty
    echo ""
    [[ -n "$SOC2_PASS_CACHED" ]] && printf '%s\n' "$SOC2_PASS_CACHED" | ssh -o LogLevel=ERROR soc2 "sudo -S -p '' -v"
}

sudo_pass_discover
printf '%s\n' "$SUDO_PASS_CACHED" | sudo -S -p '' bash -c "mkdir -p /home/$USER_NAME/.ssh && chown -R $USER_NAME:$USER_NAME /home/$USER_NAME/.ssh && find /home/$USER_NAME/.ssh -type d -exec chmod 700 {} + && find /home/$USER_NAME/.ssh -type f -exec chmod 600 {} +"

mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
if [[ ! -f "$HOME/.ssh/id_ed25519" ]]; then
    ssh-keygen -t ed25519 -f "$HOME/.ssh/id_ed25519" -N ""
fi
touch "$HOME/.ssh/config"
if ! grep -q '^Host soc2$' "$HOME/.ssh/config"; then
    cat >> "$HOME/.ssh/config" <<EOF
Host soc2
    HostName $SOC2_IP
    User $USER_NAME
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
    LogLevel ERROR
EOF
fi
chmod 600 "$HOME/.ssh/config"

copy_soc2_key
soc2_sudo_pass_discover

printf '%s\n' "$SOC2_PASS_CACHED" | ssh -T -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR soc2 "sudo -S -p '' bash -c 'mkdir -p /home/$USER_NAME/.ssh && chown -R $USER_NAME:$USER_NAME /home/$USER_NAME/.ssh && find /home/$USER_NAME/.ssh -type d -exec chmod 700 {} + && find /home/$USER_NAME/.ssh -type f -exec chmod 600 {} +'"

printf '%s\n' "$SOC2_PASS_CACHED" | ssh -T -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR soc2 "sudo -S -p '' bash -c 'config=/home/$USER_NAME/.ssh/config; touch \"\$config\"; if ! grep -q \"^Host soc1\$\" \"\$config\"; then printf \"%s\\n\" \"Host soc1\" \"    HostName $SOC1_IP\" \"    User $USER_NAME\" \"    StrictHostKeyChecking no\" \"    UserKnownHostsFile /dev/null\" \"    LogLevel ERROR\" >> \"\$config\"; fi; chown $USER_NAME:$USER_NAME \"\$config\"; chmod 600 \"\$config\"'"

if [[ -f /mnt/ufs_data/project/.mdrive_vars.sh ]]; then
    source /mnt/ufs_data/project/.mdrive_vars.sh
fi
[[ -n "${MDRIVE_VEHICLE_NAME:-}" ]] || { echo "未设置 MDRIVE_VEHICLE_NAME"; exit 1; }

if [[ "$(hostname)" != "${MDRIVE_VEHICLE_NAME}-soc1" ]]; then
    printf '%s\n' "$SUDO_PASS_CACHED" | sudo -S -p '' hostnamectl set-hostname "${MDRIVE_VEHICLE_NAME}-soc1"
fi
if [[ "$(ssh -n -o LogLevel=ERROR soc2 hostname)" != "${MDRIVE_VEHICLE_NAME}-soc2" ]]; then
    printf '%s\n' "$SOC2_PASS_CACHED" | ssh -T -o LogLevel=ERROR soc2 "sudo -S -p '' hostnamectl set-hostname '${MDRIVE_VEHICLE_NAME}-soc2'"
fi
REMOTE

    then
        ssh -T -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
            -p "$port" "$target" "rm -f -- $remote_script_q" >/dev/null 2>&1 || true
        log_err "端口 $port 的车端 SOC 配置脚本上传失败"
        return 1
    fi

    remote_command="SOC1_IP=$soc1_ip_q SOC2_IP=$soc2_ip_q USER_NAME=$user_name_q bash $remote_script_q; status=\$?; rm -f -- $remote_script_q; exit \$status"
    if ! ssh -tt -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
        -p "$port" "$target" "$remote_command"
    then
        log_err "端口 $port 的车端 SOC 配置失败"
        return 1
    fi
    log_ok "端口 $port 的 SOC 免密与主机名配置完成"
}

# sshpass 辅助分发函数：避免交互密码提示被终端屏蔽
copy_key() {
    local target="$1"                    # user@host
    local port_arg=()                   # 可选端口参数
    local label="$target"               # 用于提示

    if [ -n "${2:-}" ]; then
        port_arg=(-p "$2")
        label="$target (port $2)"
    fi

    echo ""
    log_info "正在向 $label 分发公钥..."

    # 先快速探测 TCP 连通性（不依赖 SSH 认证状态）
    local host="${target#*@}"
    local port="${2:-22}"
    if ! nc -z -w 3 "$host" "$port" 2>/dev/null; then
        log_warn "$label 端口 $port 不可达，跳过"
        return 1
    fi

    if command -v sshpass &>/dev/null; then
        if [[ -n "$SSH_PASS_CACHED" ]]; then
            if SSHPASS="$SSH_PASS_CACHED" sshpass -e ssh-copy-id -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR "${port_arg[@]}" -i "${KEY_PATH}.pub" "$target"; then
                SSHPASS="$SSH_PASS_CACHED"
                log_ok "$label 公钥分发成功"
                return 0
            fi
            SSH_PASS_CACHED=""
        fi

        local password
        for password in "${SSH_PASSWORDS[@]}"; do
            if SSHPASS="$password" sshpass -e ssh-copy-id -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR "${port_arg[@]}" -i "${KEY_PATH}.pub" "$target"; then
                SSH_PASS_CACHED="$password"
                SSHPASS="$password"
                log_ok "$label 公钥分发成功"
                return 0
            fi
        done
    fi

    # 交互式回退
    log_info "即将弹出 ssh-copy-id 密码提示，请输入远程用户密码"
    sleep 1
    if ssh-copy-id -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR "${port_arg[@]}" -i "${KEY_PATH}.pub" "$target"; then
        read -rsp "  请输入 $label 的密码（用于 sudo）: " SSH_PASS_CACHED
        echo ""
        SSHPASS="$SSH_PASS_CACHED"
        log_ok "$label 公钥分发成功"
        return 0
    else
        log_err "$label 公钥分发失败，请检查密码或网络"
        return 1
    fi
}

# 远端 ~/.ssh 权限修复：owner -> USER_NAME，目录 700，文件 600
repair_remote_ssh() {
    local target="$1"
    local port_arg=()
    local label="$target"

    if [ -n "${2:-}" ]; then
        port_arg=(-p "$2")
        label="$target (port $2)"
    fi

    local remote_cmd="sudo -S bash -c 'mkdir -p /home/${USER_NAME}/.ssh && chown -R ${USER_NAME}:${USER_NAME} /home/${USER_NAME}/.ssh && find /home/${USER_NAME}/.ssh -type d -exec chmod 700 {} + && find /home/${USER_NAME}/.ssh -type f -exec chmod 600 {} +'"

    echo ""
    log_info "正在修复 $label 的 ~/.ssh 权限与归属..."

    if [ -n "${SSHPASS:-}" ]; then
        if printf '%s\n' "$SSHPASS" | ssh -T -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR "${port_arg[@]}" "$target" "$remote_cmd" >/dev/null 2>&1; then
            log_ok "$label ~/.ssh 权限修复成功"
            return 0
        fi
    fi

    log_err "$label ~/.ssh 权限修复失败，请登录远端手动执行 sudo chown/chmod"
    return 1
}

# [2/3] 配置 ~/.ssh/config
log_info "配置 SSH config..."
if [ "$MODE" == "1" ]; then
    # 局域网模式配置
    if ! grep -q "Host soc1" "$CONFIG_PATH" 2>/dev/null; then
        cat << EOF >> "$CONFIG_PATH"
Host soc1
    HostName $SOC1_IP
    User $USER_NAME
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
    LogLevel ERROR

Host soc2
    HostName $SOC2_IP
    User $USER_NAME
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
    LogLevel ERROR
EOF
        log_ok "  已添加 soc1 / soc2 配置到 $CONFIG_PATH"
    else
        log_ok "  soc1 / soc2 配置已存在"
    fi
    TARGET_IPS="$SOC1_IP $SOC2_IP"
else
    # 公网模式配置
    read -rp "  请输入公网映射端口 (多个用空格隔开): " WAN_PORTS
    TARGET_WAN="$WAN_PORTS"
fi
chmod 600 "$CONFIG_PATH"

# [3/3] 分发公钥
log_info "分发公钥..."

# 在最终 ssh-copy-id 操作中依次尝试缓存和预设密码。
if ! command -v sshpass &>/dev/null; then
    log_info "  未安装 sshpass，将使用交互式 ssh-copy-id。"
fi

fail_count=0
if [ "$MODE" == "1" ]; then
    # 局域网分发
    for IP in $TARGET_IPS; do
        ssh-keygen -f "$HOME/.ssh/known_hosts" -R "$IP" 2>/dev/null
        if ! copy_key "$USER_NAME@$IP" || ! repair_remote_ssh "$USER_NAME@$IP"; then
            ((fail_count++))
        fi
    done
else
    # 公网分发
    for PORT in $TARGET_WAN; do
        ssh-keygen -f "$HOME/.ssh/known_hosts" -R "[$WAN_DOMAIN]:$PORT" 2>/dev/null
        if ! copy_key "$USER_NAME@$WAN_DOMAIN" "$PORT" || ! repair_remote_ssh "$USER_NAME@$WAN_DOMAIN" "$PORT" || ! configure_vehicle "$PORT"; then
            ((fail_count++))
        fi
    done
fi

unset SSHPASS

echo ""
if [ "$fail_count" -eq 0 ]; then
    if [ "$MODE" == "1" ]; then
        log_ok "全部配置完成！现在可以使用 ssh soc1 / ssh soc2 登录"
    else
        log_ok "全部配置完成！"
    fi
else
    log_warn "$fail_count 个目标分发失败，请检查网络/密码后重试"
fi
