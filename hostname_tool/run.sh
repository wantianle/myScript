#!/usr/bin/env bash
set -euo pipefail

USER_NAME="nvidia"
SOC2_IP="192.168.10.3"
WAN_DOMAIN="ad.minieye.tech"
KEY_PATH="$HOME/.ssh/id_ed25519"
HOSTNAME_PASS="mini!@#123.com"

ensure_local_key() {
    mkdir -p "$HOME/.ssh"
    chmod 700 "$HOME/.ssh"

    if [ ! -f "$KEY_PATH" ]; then
        echo "[1/3] 未发现密钥，正在生成默认密钥..."
        ssh-keygen -t ed25519 -f "$KEY_PATH" -N ""
    else
        echo "[1/3] 密钥已存在，跳过生成步骤。"
    fi
}

config_soc2_on_soc1() {
    local display_target="$1"
    local target="$2"
    local port="$3"

    echo "配置 SOC1 -> SOC2 免密：$display_target -> $USER_NAME@$SOC2_IP"
    ssh -tt \
        -o LogLevel=ERROR \
        -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null \
        -p "$port" \
        "$target" \
        "LC_ALL=C LANG=C SOC2_IP=$SOC2_IP USER_NAME=$USER_NAME bash -c '
set -e

KEY_PATH=\"\$HOME/.ssh/id_ed25519\"
CONFIG_PATH=\"\$HOME/.ssh/config\"

mkdir -p \"\$HOME/.ssh\"
chmod 700 \"\$HOME/.ssh\"

if [ ! -f \"\$KEY_PATH\" ]; then
    echo \"未发现密钥，正在生成默认密钥...\"
    ssh-keygen -t ed25519 -f \"\$KEY_PATH\" -N \"\"
fi

if ! ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \"\$USER_NAME@\$SOC2_IP\" true 2>/dev/null; then
    echo \"推送公钥到soc2：\$USER_NAME@\$SOC2_IP...\"
    ssh-copy-id -o LogLevel=ERROR -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i \"\${KEY_PATH}.pub\" \"\$USER_NAME@\$SOC2_IP\"
fi

touch \"\$CONFIG_PATH\"
if ! grep -q \"^Host soc2\$\" \"\$CONFIG_PATH\"; then
    echo \"配置 soc2 快捷登录：ssh soc2\"
    cat << EOF >> \"\$CONFIG_PATH\"
# Orin SOC2 快捷登录
Host soc2
    HostName \$SOC2_IP
    User \$USER_NAME
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
EOF
    chmod 600 \"\$CONFIG_PATH\"
fi
'"
}

distribute_key() {
    local port="$1"

    echo "[2/3] 正在分发公钥到端口 $port ..."
    ssh-keygen -f "$HOME/.ssh/known_hosts" -R "[$WAN_DOMAIN]:$port" 2>/dev/null || true
    ssh-copy-id -o StrictHostKeyChecking=no -p "$port" -i "${KEY_PATH}.pub" "$USER_NAME@$WAN_DOMAIN"
    config_soc2_on_soc1 "$USER_NAME@$WAN_DOMAIN:$port" "$USER_NAME@$WAN_DOMAIN" "$port"
}

set_remote_hostname() {
    local port="$1"

    echo "[3/3] 正在设置车端主机名..."
    ssh \
        -o StrictHostKeyChecking=no \
        -o LogLevel=ERROR \
        -o UserKnownHostsFile=/dev/null \
        -p "$port" \
        "$USER_NAME@$WAN_DOMAIN" \
        "LC_ALL=C LANG=C PASS='$HOSTNAME_PASS' bash -s" <<'SOC1'
set -e

if [ -f /mnt/ufs_data/project/.mdrive_vars.sh ]; then
    source /mnt/ufs_data/project/.mdrive_vars.sh
fi

VEH_NAME="$MDRIVE_VEHICLE_NAME"
[ -n "$VEH_NAME" ] || { echo "source /mnt/ufs_data/project/.mdrive_vars.sh 后仍未设置 MDRIVE_VEHICLE_NAME"; exit 1; }
echo "$PASS" | sudo -S hostnamectl set-hostname "${VEH_NAME}-soc1"
ssh -o LogLevel=ERROR soc2 "echo '$PASS' | sudo -S hostnamectl set-hostname '${VEH_NAME}-soc2'"
SOC1
}

main() {
    local port="${1:-}"

    if [ -z "$port" ]; then
        read -rp "请输入公网映射端口: " port
    fi

    if [ -z "$port" ]; then
        echo "用法: $0 <车端SSH映射端口>"
        exit 1
    fi

    echo "--------------本机到车端免密配置与主机名设置--------------"
    echo "目标: $USER_NAME@$WAN_DOMAIN:$port"

    ensure_local_key
    distribute_key "$port"
    set_remote_hostname "$port"

    echo "配置完成！车端免密和主机名已设置完成。"
}

main "$@"
