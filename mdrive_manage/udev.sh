#!/bin/bash

# ====================================================
# 脚本名称: setup_disk_auto_repair.sh
# 功能: 备份旧规则，创建基于 udev+systemd 的自动修复挂载环境
# ====================================================

# 确保以 root 权限运行
if [ "$EUID" -ne 0 ]; then
    echo "请使用 sudo 运行此脚本"
    exit 1
fi

NV_AUTOMOUNT="/etc/udev/rules.d/99-nv_usb-automount_default.rules"
UDEV_RULE_PATH="/etc/udev/rules.d/99-disk-auto-repair.rules"
SERVICE_PATH="/etc/systemd/system/disk-repair@.service"
REPAIR_SCRIPT="/usr/local/bin/disk-repair-tool.sh"
LOG_PATH="/var/log/disk_auto_repair.log"
MOUNT_ROOT="/media/data"

echo "--- 开始环境部署 ---"

echo "清除残留规则/服务/日志"
sudo rm -f "$UDEV_RULE_PATH" "$SERVICE_PATH" "$REPAIR_SCRIPT" "$LOG_PATH"

if [ -f "$NV_AUTOMOUNT" ]; then
    mv "$NV_AUTOMOUNT" "$NV_AUTOMOUNT.bak"
    echo "已备份: $(basename $NV_AUTOMOUNT)"
fi

echo "正在创建修复脚本: $REPAIR_SCRIPT"
cat << 'EOF' > "$REPAIR_SCRIPT"
#!/bin/bash
export PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin

DEV_NAME=$1
DEVICE="/dev/$DEV_NAME"
MOUNT_POINT="/media/data"
SSH_QUICK="-o ConnectTimeout=2 -o ServerAliveInterval=2 -o ServerAliveCountMax=1 -o BatchMode=yes"
REMOTE_HOST="nvidia@192.168.10.3"

exec >> /var/log/disk_auto_repair.log 2>&1
echo "[$(date)]"
echo "开始处理设备: $DEVICE"

if [ ! -b "$DEVICE" ]; then
    echo "错误: $DEVICE 不是有效的块设备"
    exit 1
fi

echo "正在运行e2fsck修复..."
/sbin/e2fsck -yf "$DEVICE"

if [[ -d "$MOUNT_POINT" ]]; then
    findmnt -n -o SOURCE "$MOUNT_ROOT"
    echo -e "正在清理挂载点..."
    while mountpoint -q $MOUNT_POINT; do
        sudo umount -l $MOUNT_POINT
    done
else
    mkdir -p "$MOUNT_POINT"
fi

if /bin/mount "$DEVICE" "$MOUNT_POINT"; then
    ssh $SSH_QUICK -n "$REMOTE_HOST" "sudo umount -fl /media/data; sudo systemctl restart media-data.mount" &
    echo "挂载成功: $MOUNT_POINT"
else
    echo "挂载失败"
fi
echo "--------------------------------------"
EOF

chmod +x "$REPAIR_SCRIPT"

# 创建 Systemd 模板服务
echo "正在创建模板服务: $SERVICE_PATH"
cat << EOF > "$SERVICE_PATH"
[Unit]
Description=Auto Repair and Mount Disk %I
After=local-fs.target

[Service]
Type=oneshot
ExecStart=$REPAIR_SCRIPT %i
RemainAfterExit=no
TimeoutStartSec=30

[Install]
WantedBy=multi-user.target
EOF

# 创建 udev 规则
echo "正在创建 udev 规则: $UDEV_RULE_PATH"
cat << EOF > "$UDEV_RULE_PATH"
ACTION=="add", SUBSYSTEM=="block", KERNEL=="sd[a-z][0-9]", TAG+="systemd", ENV{SYSTEMD_WANTS}="disk-repair@%k.service"
EOF

# 刷新系统配置
echo "正在刷新系统配置..."
systemctl daemon-reload
udevadm control --reload-rules
udevadm trigger

echo "部署完成"
echo -E "日志文件位置: $LOG_PATH"
echo -E "现在插入磁盘仓或重启设备，系统将自动检查并挂载至 $MOUNT_ROOT"
