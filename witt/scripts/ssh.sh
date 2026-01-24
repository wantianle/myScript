#!/bin/bash

USER_NAME="nvidia"
SOC1_IP="192.168.10.2"
SOC2_IP="192.168.10.3"
KEY_PATH="$HOME/.ssh/id_ed25519"
CONFIG_PATH="$HOME/.ssh/config"

echo "开始配置 SSH 环境..."
if [ ! -f "$KEY_PATH" ]; then
    echo "[1/3] 未发现密钥，正在生成默认密钥..."
    ssh-keygen -t ed25519 -f "$KEY_PATH" -N ""
else
    echo "[1/3] 密钥已存在，跳过生成步骤。"
fi

echo "[2/3] 正在配置 ~/.ssh/config..."
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

echo "[3/3] 正在分发公钥 (如果提示输入密码，请输入 $USER_NAME 的登录密码)..."

for IP in $SOC1_IP $SOC2_IP; do
    echo "正在处理: $IP ..."
    ssh-keygen -f "$HOME/.ssh/known_hosts" -R "192.168.10.2"
    ssh-keygen -f "$HOME/.ssh/known_hosts" -R "192.168.10.3"
    # 使用 -o 参数确保 ssh-copy-id 过程中也不检查指纹
    ssh-copy-id -o StrictHostKeyChecking=no -i "${KEY_PATH}.pub" "$USER_NAME@$IP"
    if [ $? -eq 0 ]; then
        echo "$IP 公钥上传成功！"
    else
        echo "$IP 公钥上传失败，请检查网络或密码。"
    fi
done

echo "---------------------------"
echo "通过以下命令免密登录："
echo "  ssh soc1"
echo "  ssh soc2"
echo "---------------------------"
