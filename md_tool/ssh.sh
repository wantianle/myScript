#!/usr/bin/env bash

USER_NAME="nvidia"
SOC1_IP="192.168.10.2"
SOC2_IP="192.168.10.3"
WAN_DOMAIN="ad.minieye.tech"
KEY_PATH="$HOME/.ssh/id_ed25519"
CONFIG_PATH="$HOME/.ssh/config"

RED='\033[1;31m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_err()  { echo -e "${RED}[ERROR]${NC} $1"; }

echo -e "${BLUE}===============================================${NC}"
echo -e "  ${GREEN}1)${NC} 局域网免密  (SOC1: ${YELLOW}.10.2${NC}, SOC2: ${YELLOW}.10.3${NC})"
echo -e "  ${GREEN}2)${NC} 公网批量免密 (域名: ${YELLOW}ad.minieye.tech${NC})"
echo -e "${BLUE}===============================================${NC}"
read -rp "  请选择模式 [1/2]: " MODE
echo ""

# [1/3] 密钥生成逻辑
log_info "检查本地密钥..."
if [ ! -f "$KEY_PATH" ]; then
    log_info "  未发现密钥，正在生成 ed25519 密钥对..."
    ssh-keygen -t ed25519 -f "$KEY_PATH" -N "" 2>&1 | while IFS= read -r line; do
        echo "        $line"
    done
    log_ok "  密钥已生成: $KEY_PATH"
else
    log_ok "  密钥已存在: $KEY_PATH"
fi

mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"

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

    if [ -n "${SSHPASS:-}" ]; then
        # 使用 sshpass 非交互式分发
        if sshpass -e ssh-copy-id -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR "${port_arg[@]}" -i "${KEY_PATH}.pub" "$target"; then
            log_ok "$label 公钥分发成功"
            return 0
        else
            log_err "$label sshpass 分发失败，尝试交互式..."
        fi
    fi

    # 交互式回退
    log_info "即将弹出 ssh-copy-id 密码提示，请输入远程用户密码"
    sleep 1
    if ssh-copy-id -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR "${port_arg[@]}" -i "${KEY_PATH}.pub" "$target"; then
        log_ok "$label 公钥分发成功"
        return 0
    else
        log_err "$label 公钥分发失败，请检查密码或网络"
        return 1
    fi
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
    for PORT in $WAN_PORTS; do
        if ! grep -q "Host soc_$PORT" "$CONFIG_PATH" 2>/dev/null; then
            cat << EOF >> "$CONFIG_PATH"
Host soc$PORT
    HostName $WAN_DOMAIN
    Port $PORT
    User $USER_NAME
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
    LogLevel ERROR
EOF
            log_ok "  已添加 soc$PORT -> $WAN_DOMAIN:$PORT"
        else
            log_ok "  soc$PORT 配置已存在"
        fi
    done
    TARGET_WAN="$WAN_PORTS"
fi
chmod 600 "$CONFIG_PATH"

# [3/3] 分发公钥
log_info "分发公钥..."

# 尝试用 sshpass 避免交互密码提示被终端吞掉
if command -v sshpass &>/dev/null; then
    read -rsp "  请输入远程主机 ($USER_NAME) 的密码 (直接回车使用交互式): " SSHPASS
    echo ""
fi
if [ -z "${SSHPASS:-}" ]; then
    log_info "  将使用交互式 ssh-copy-id，请留意终端密码提示。"
fi
export SSHPASS

fail_count=0
if [ "$MODE" == "1" ]; then
    # 局域网分发
    for IP in $TARGET_IPS; do
        ssh-keygen -f "$HOME/.ssh/known_hosts" -R "$IP" 2>/dev/null
        if ! copy_key "$USER_NAME@$IP"; then
            ((fail_count++))
        fi
    done
else
    # 公网分发
    for PORT in $TARGET_WAN; do
        ssh-keygen -f "$HOME/.ssh/known_hosts" -R "[$WAN_DOMAIN]:$PORT" 2>/dev/null
        if ! copy_key "$USER_NAME@$WAN_DOMAIN" "$PORT"; then
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
        log_ok "全部配置完成！现在可以使用 ssh soc端口号 (例如: ssh soc6171) 登录"
    fi
else
    log_warn "$fail_count 个目标分发失败，请检查网络/密码后重试"
fi
