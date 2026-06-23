#!/usr/bin/env bash

USER_NAME="nvidia"
SOC1_IP="192.168.10.2"
SOC2_IP="192.168.10.3"
KEY_PATH="$HOME/.ssh/id_ed25519"
CONFIG_PATH="$HOME/.ssh/config"

echo "[INFO] 开始配置 SSH 环境..."
if [ ! -f "$KEY_PATH" ]; then
    echo "[INFO] 未发现密钥，正在生成默认密钥..."
    ssh-keygen -t ed25519 -f "$KEY_PATH" -N ""
else
    echo "[OK] 密钥已存在，跳过生成步骤。"
fi

echo "[INFO] 正在配置 ~/.ssh/config..."
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"

if ! grep -q "Host soc1" "$CONFIG_PATH"; then
    cat << EOF >> "$CONFIG_PATH"
# Orin SOC1 快捷登录
Host soc1
    HostName $SOC1_IP
    User $USER_NAME
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
    LogLevel ERROR

# Orin SOC2 快捷登录
Host soc2
    HostName $SOC2_IP
    User $USER_NAME
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
    LogLevel ERROR
EOF
fi
chmod 600 "$CONFIG_PATH"

echo "[INFO] 正在分发公钥 (如果提示输入密码，请输入 $USER_NAME 的登录密码)..."

for IP in $SOC1_IP $SOC2_IP; do
    echo "[INFO] 正在处理: $IP ..."

    # 先快速探测 TCP 连通性，避免不通时 ssh-copy-id 长时间卡死
    if ! nc -z -w 3 "$IP" 22 2>/dev/null; then
        echo "[ERROR] $IP 端口不可达，跳过"
        continue
    fi

    ssh-keygen -f "$HOME/.ssh/known_hosts" -R "$IP" 2>/dev/null
    # -o ConnectTimeout 防止 TCP 层面卡死
    # -o StrictHostKeyChecking=no 跳过指纹确认
    if ssh-copy-id -o ConnectTimeout=5 -o StrictHostKeyChecking=no -i "${KEY_PATH}.pub" "$USER_NAME@$IP"; then
        echo "[OK] $IP 公钥上传成功"
    else
        echo "[ERROR] $IP 公钥上传失败，请检查网络或密码"
    fi
done

echo "---------------------------"
echo "通过以下命令免密登录："
echo "  ssh soc1"
echo "  ssh soc2"
echo "---------------------------"
