#!/bin/bash

USER_NAME="nvidia"
SOC1_IP="192.168.10.2"
SOC2_IP="192.168.10.3"
WAN_DOMAIN="ad.minieye.tech"
KEY_PATH="$HOME/.ssh/id_ed25519"
CONFIG_PATH="$HOME/.ssh/config"

echo "-----------------------------------------------"
echo "1) 局域网免密 (SOC1: .10.2, SOC2: .10.3)"
echo "2) 公网批量免密 (域名: ad.minieye.tech)"
read -rp "请选择模式 [1/2]: " MODE
echo "-----------------------------------------------"

# [1/3] 密钥生成逻辑
if [ ! -f "$KEY_PATH" ]; then
    echo "[1/3] 未发现密钥，正在生成默认密钥..."
    ssh-keygen -t ed25519 -f "$KEY_PATH" -N ""
else
    echo "[1/3] 密钥已存在，跳过生成步骤。"
fi

mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"

# [2/3] 配置 ~/.ssh/config
if [ "$MODE" == "1" ]; then
    # 局域网模式配置
    if ! grep -q "Host soc1" "$CONFIG_PATH" 2>/dev/null; then
        cat << EOF >> "$CONFIG_PATH"
Host soc1
    HostName $SOC1_IP
    User $USER_NAME
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null

Host soc2
    HostName $SOC2_IP
    User $USER_NAME
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
EOF
    fi
    TARGET_IPS="$SOC1_IP $SOC2_IP"
else
    # 公网模式配置
    read -rp "请输入公网映射端口(多个用空格隔开): " WAN_PORTS
    TARGET_WAN="$WAN_PORTS"
fi
chmod 600 "$CONFIG_PATH"

# [3/3] 分发公钥
echo "[3/3] 正在分发公钥..."

if [ "$MODE" == "1" ]; then
    # 局域网分发
    for IP in $TARGET_IPS; do
        ssh-keygen -f "$HOME/.ssh/known_hosts" -R "$IP" 2>/dev/null
        ssh-copy-id -o StrictHostKeyChecking=no -i "${KEY_PATH}.pub" "$USER_NAME@$IP"
    done
    echo "配置完成！现在可以使用 ssh soc1 / ssh soc2 登录"
else
    # 公网分发
    for PORT in $TARGET_WAN; do
        echo "正在处理端口: $PORT ..."
        ssh-keygen -f "$HOME/.ssh/known_hosts" -R "[$WAN_DOMAIN]:$PORT" 2>/dev/null
        ssh-copy-id -o StrictHostKeyChecking=no -p "$PORT" -i "${KEY_PATH}.pub" "$USER_NAME@$WAN_DOMAIN"
    done
    echo "配置完成！"
fi
