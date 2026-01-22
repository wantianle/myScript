#!/bin/bash

USER_NAME="nvidia"
SOC1_IP="192.168.10.2"
SOC2_IP="192.168.10.3"
KEY_PATH="$HOME/.ssh/id_ed25519"
CONFIG_PATH="$HOME/.ssh/config"

echo "开始配置 SSH 环境..."

# 1. 如果没有密钥，则生成默认密钥 (ed25519)
if [ ! -f "$KEY_PATH" ]; then
    echo "[1/3] 未发现密钥，正在生成默认密钥..."
    ssh-keygen -t ed25519 -f "$KEY_PATH" -N ""
else
    echo "[1/3] 密钥已存在，跳过生成步骤。"
fi

# 2. 配置 ~/.ssh/config 自动跳过指纹并设置别名
echo "[2/3] 正在配置 ~/.ssh/config..."
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"

# 使用了 StrictHostKeyChecking=no 和 /dev/null 来彻底不保存指纹
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
echo "Config 配置完成！别名：soc1, soc2"

# 3. 上传公钥到 SOC1 和 SOC2
echo "[3/3] 正在分发公钥 (如果提示输入密码，请输入 $USER_NAME 的登录密码)..."

for IP in $SOC1_IP $SOC2_IP; do
    echo "正在处理: $IP ..."
    # 使用 -o 参数确保 ssh-copy-id 过程中也不检查指纹
    ssh-copy-id -o StrictHostKeyChecking=no -i "${KEY_PATH}.pub" "$USER_NAME@$IP"
    if [ $? -eq 0 ]; then
        echo "✅ $IP 公钥上传成功！"
    else
        echo "❌ $IP 公钥上传失败，请检查网络或密码。"
    fi
done

echo "------------------------------------------------"
echo "恭喜！现在你可以直接通过以下命令免密登录了："
echo "  ssh soc1"
echo "  ssh soc2"
echo "------------------------------------------------"
