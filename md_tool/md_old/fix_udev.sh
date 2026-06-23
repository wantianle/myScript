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
SCAN_SERVICE_PATH="/etc/systemd/system/disk-repair-scan.service"
REPAIR_SCRIPT="/usr/local/bin/disk-repair-tool.sh"
SCAN_SCRIPT="/usr/local/bin/disk-repair-scan.sh"
LOG_PATH="/var/log/disk_auto_repair.log"
MOUNT_ROOT="/media/data"

echo "--- 开始环境部署 ---"

echo "清除残留规则/服务/脚本（保留历史日志）"
sudo rm -f "$UDEV_RULE_PATH" "$SERVICE_PATH" "$SCAN_SERVICE_PATH" "$REPAIR_SCRIPT" "$SCAN_SCRIPT"

if [ -f "$NV_AUTOMOUNT" ]; then
    mv "$NV_AUTOMOUNT" "$NV_AUTOMOUNT.bak"
    echo "已备份: $(basename "$NV_AUTOMOUNT")"
fi

echo "正在创建修复脚本: $REPAIR_SCRIPT"
cat << 'EOF' > "$REPAIR_SCRIPT"
#!/bin/bash
export PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin

DEV_NAME=$1
DEVICE="/dev/$DEV_NAME"
MOUNT_POINT="/media/data"
LOCK_FILE="/run/disk-repair-tool.lock"
SSH_OPTS=(
    -o ConnectTimeout=2
    -o ServerAliveInterval=2
    -o ServerAliveCountMax=1
    -o BatchMode=yes
    -o StrictHostKeyChecking=no
    -o UserKnownHostsFile=/dev/null
)
IDENTITY=(-i /home/nvidia/.ssh/id_ed25519)
REMOTE_HOST="nvidia@192.168.10.3"

exec >> /var/log/disk_auto_repair.log 2>&1
echo "[$(date)]"
echo "开始处理设备: $DEVICE"

exec 9>"$LOCK_FILE"
flock 9

if [ ! -b "$DEVICE" ]; then
    echo "错误: $DEVICE 不是有效的块设备"
    exit 1
fi

log() {
    echo "[$(date '+%F %T')] $*"
}

same_device() {
    local left=$1
    local right=$2

    [ "$(readlink -f "$left")" = "$(readlink -f "$right")" ]
}

device_mounted_at_mount_point() {
    local current_source

    current_source=$(findmnt -rn -o SOURCE --target "$MOUNT_POINT" 2>/dev/null || true)
    [ -n "$current_source" ] && same_device "$current_source" "$DEVICE"
}

sync_remote_mount() {
    if ssh "${SSH_OPTS[@]}" "${IDENTITY[@]}" "$REMOTE_HOST" "sudo umount -fl /media/data; sudo systemctl restart media-data.mount"; then
        log "soc1&soc2挂载同步成功: $MOUNT_POINT"
        return 0
    fi

    log "警告: 远端挂载同步失败，本机已继续保留当前状态"
    return 1
}

prepare_mount_point() {
    local current_source

    mkdir -p "$MOUNT_POINT"

    while mountpoint -q "$MOUNT_POINT"; do
        current_source=$(findmnt -rn -o SOURCE --target "$MOUNT_POINT" 2>/dev/null || true)
        if same_device "$current_source" "$DEVICE"; then
            log "$DEVICE 已挂载在 $MOUNT_POINT"
            return 0
        fi

        log "$MOUNT_POINT 已被 $current_source 占用，先卸载"
        if ! umount "$MOUNT_POINT"; then
            log "普通卸载失败，执行懒卸载: $MOUNT_POINT"
            umount -l "$MOUNT_POINT" || return 1
        fi
    done
}

unmount_device() {
    local targets
    local target

    mapfile -t targets < <(findmnt -rn -S "$DEVICE" -o TARGET)
    for target in "${targets[@]}"; do
        if [ -z "$target" ]; then
            continue
        fi

        log "$DEVICE 当前挂载在 $target，fsck 前先卸载"
        if ! umount "$target"; then
            log "普通卸载失败，执行懒卸载: $target"
            umount -l "$target" || return 1
        fi
    done
}

mount_device() {
    local stage=$1

    prepare_mount_point || return 1
    if device_mounted_at_mount_point; then
        log "$stage 已处于挂载状态: $DEVICE -> $MOUNT_POINT"
        sync_remote_mount
        return 0
    fi

    if /bin/mount "$DEVICE" "$MOUNT_POINT"; then
        log "$stage 挂载成功: $DEVICE -> $MOUNT_POINT"
        sync_remote_mount
        return 0
    fi

    log "$stage 挂载失败: $DEVICE"
    return 1
}

fsck_needs_force() {
    local rc=$1

    (( rc & 4 || rc & 8 || rc & 16 || rc & 32 || rc & 128 ))
}

run_preen_fsck() {
    local rc

    log "开始保守自动修复: e2fsck -f -p $DEVICE"
    /sbin/e2fsck -f -p "$DEVICE" </dev/null
    rc=$?
    log "e2fsck -p 退出码: $rc"
    return "$rc"
}

run_force_fsck() {
    local rc

    log "开始强制无人值守修复: e2fsck -f -y $DEVICE"
    /sbin/e2fsck -f -y "$DEVICE" </dev/null
    rc=$?
    log "e2fsck -y 退出码: $rc"
    return "$rc"
}

FSTYPE=$(blkid -o value -s TYPE "$DEVICE" 2>/dev/null || true)
case "$FSTYPE" in
    ext2|ext3|ext4)
        log "识别到文件系统: $FSTYPE"
        ;;
    "")
        log "警告: 未识别到文件系统类型，按无人值守 ext 修复流程继续"
        ;;
    *)
        log "错误: $DEVICE 是 $FSTYPE，不执行 e2fsck"
        exit 1
        ;;
esac

if mount_device "直接"; then
    echo "--------------------------------------"
    exit 0
fi

unmount_device || {
    log "错误: 无法卸载 $DEVICE，拒绝在挂载状态下 fsck"
    echo "--------------------------------------"
    exit 1
}

if mount_device "卸载已有挂载后"; then
    echo "--------------------------------------"
    exit 0
fi

run_preen_fsck
preen_rc=$?

if ! fsck_needs_force "$preen_rc"; then
    if mount_device "保守修复后"; then
        echo "--------------------------------------"
        exit 0
    fi
fi

run_force_fsck
force_rc=$?

if fsck_needs_force "$force_rc"; then
    log "错误: 强制修复后仍存在未解决问题，退出码: $force_rc"
    echo "--------------------------------------"
    exit "$force_rc"
fi

if ! mount_device "强制修复后"; then
    log "错误: 强制修复完成但仍无法挂载"
    echo "--------------------------------------"
    exit 1
fi

echo "--------------------------------------"
EOF

chmod +x "$REPAIR_SCRIPT"

echo "正在创建开机扫描脚本: $SCAN_SCRIPT"
cat << 'EOF' > "$SCAN_SCRIPT"
#!/bin/bash
export PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin

LOG_PATH="/var/log/disk_auto_repair.log"
SCAN_SECONDS=30
SLEEP_SECONDS=2

exec >> "$LOG_PATH" 2>&1

log() {
    echo "[$(date '+%F %T')] $*"
}

start_partition_service() {
    local part_name=$1

    log "开机/部署扫描发现分区: /dev/$part_name"
    systemctl start --no-block "disk-repair@$part_name.service"
}

log "开始扫描当前 sd 磁盘分区"

declare -A started=()
end_time=$((SECONDS + SCAN_SECONDS))

while [ "$SECONDS" -le "$end_time" ]; do
    for part_path in /sys/block/sd*/sd*[0-9]; do
        if [ ! -e "$part_path" ]; then
            continue
        fi

        part_name=$(basename "$part_path")
        if [ -n "${started[$part_name]+x}" ]; then
            continue
        fi

        started["$part_name"]=1
        start_partition_service "$part_name"
    done

    sleep "$SLEEP_SECONDS"
done

if [ "${#started[@]}" -eq 0 ]; then
    log "扫描结束: 未发现 sd 磁盘分区"
else
    log "扫描结束: 已启动 ${#started[@]} 个分区处理任务"
fi
EOF

chmod +x "$SCAN_SCRIPT"

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
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF

echo "正在创建开机扫描服务: $SCAN_SERVICE_PATH"
cat << EOF > "$SCAN_SERVICE_PATH"
[Unit]
Description=Scan Existing Disks for Auto Repair and Mount
After=local-fs.target systemd-udevd.service

[Service]
Type=oneshot
ExecStart=$SCAN_SCRIPT
RemainAfterExit=no
TimeoutStartSec=0

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

echo "启用开机扫描服务并立即扫描当前磁盘..."
systemctl enable "$SCAN_SERVICE_PATH"
systemctl start --no-block disk-repair-scan.service
echo "已重新加载 udev 规则；新插入磁盘将自动处理"

echo "部署完成"
echo -E "日志文件位置: $LOG_PATH"
echo -E "现在插入磁盘仓或重启设备，系统将自动检查并挂载至 $MOUNT_ROOT"
