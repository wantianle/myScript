#!/bin/bash

# 颜色
G='\033[0;32m'
R='\033[0;31m'
B='\033[0;34m'
NC='\033[0m'
CRED_DIR="/etc/creds"
CRED_FILE="$CRED_DIR/nas.cred"
reconfig=""

if [[ $EUID -ne 0 ]]; then
   echo -e "${R}❌ 请使用 sudo 运行${NC}"
   exit 1
fi

mkdir -p "$CRED_DIR" 2>/dev/null

if ! command -v mount.cifs &> /dev/null; then
    echo -e "${B}🚀 安装 cifs-utils...${NC}"
    apt-get update && apt-get install cifs-utils -y
fi

echo "----------- ⚡ 开始部署 NAS 自动挂载服务 -----------"
if [[ -f "$CRED_FILE" ]]; then
    while [[ ! "$reconfig" =~ ^[yYnN]$ ]]; do
        read -p "发现已存在配置文件 $CRED_FILE，是否重新配置? (y/n/v查看，直接回车默认 n): " choice
        choice=${choice:-n}
        if [[ "$choice" == "v" ]]; then
            echo -e "${B}🔐 当前凭证:${NC}"
            cat "$CRED_FILE"
            continue
        fi

        if [[ "$choice" =~ ^[yYnN]$ ]]; then
            reconfig="$choice"
        else
            echo -e "${R}❌ 无效选择${NC}"
        fi
    done
fi
if [[ "$reconfig" =~ ^[yY]$ ]] || [[ -z $reconfig ]]; then
    read -p "👤 请输入 OA 用户名: " nas_user
    nas_user=${nas_user:-mini}
    read -sp "🔑 请输入 OA 密码: " nas_pass
    echo
    cat <<EOL > "$CRED_FILE"
username=$nas_user
password=$nas_pass
EOL
    chmod 600 "$CRED_FILE"
    echo -e "${G}✅ 凭证已生成${NC}"
else
    echo -e "${G}✅ 保留现有配置${NC}"
fi

echo "请选择需要挂载的 NAS:"
echo "  1) 数据服务器 //hfs.minieye.tech/ad-data -> /media/nas"
echo "  2) 文档服务器 //hfs.minieye.tech/ad-doc  -> /media/doc"
echo "  3) WWW 服务器 //hfs.minieye.tech/ad-www -> /media/www"
echo "  4) PNC 规划服务器 //hfs.minieye.tech/department-pnc_team-planning_algo-driving -> /media/pnc"
echo "可输入多个选项，以空格分隔（例如：1 3 4）"

while true; do
    read -r -a nas_choices -p "请输入选项 (1/2/3/4): "
    if (( ${#nas_choices[@]} == 0 )); then
        echo -e "${R}❌ 请至少选择一个 NAS${NC}"
        continue
    fi

    declare -A selected_options=()
    selected_options=()
    selected_choices=()
    valid_choices=1
    for nas_choice in "${nas_choices[@]}"; do
        if [[ ! "$nas_choice" =~ ^[1-4]$ ]]; then
            echo -e "${R}❌ 无效选项: $nas_choice（仅支持 1、2、3、4）${NC}"
            valid_choices=0
            break
        fi
        if [[ -z ${selected_options[$nas_choice]+x} ]]; then
            selected_options[$nas_choice]=1
            selected_choices+=("$nas_choice")
        fi
    done

    (( valid_choices == 1 )) && break
done

MOUNT_ITEMS=""
MOUNT_POINTS=""
for nas_choice in "${selected_choices[@]}"; do
    case "$nas_choice" in
        1)
            MOUNT_ITEMS+='"data|//hfs.minieye.tech/ad-data|/media/nas" '
            MOUNT_POINTS+="/media/nas "
            ;;
        2)
            MOUNT_ITEMS+='"doc|//hfs.minieye.tech/ad-doc|/media/doc" '
            MOUNT_POINTS+="/media/doc "
            ;;
        3)
            MOUNT_ITEMS+='"www|//hfs.minieye.tech/ad-www|/media/www" '
            MOUNT_POINTS+="/media/www "
            ;;
        4)
            MOUNT_ITEMS+='"pnc|//hfs.minieye.tech/department-pnc_team-planning_algo-driving|/media/pnc" '
            MOUNT_POINTS+="/media/pnc "
            ;;
    esac
done
MOUNT_ITEMS=${MOUNT_ITEMS% }
MOUNT_POINTS=${MOUNT_POINTS% }

for mount_point in $MOUNT_POINTS; do
    mkdir -p "$mount_point"
done

HELPER="/usr/local/bin/nasmount_helper.sh"
Cleanup="/usr/local/bin/nasmount_cleanup.sh"

# Generate selection-specific cleanup rather than relying on a unit file with
# hard-coded mount points.  Reinstalling replaces this file with the current
# selection.
cat <<EOL > "$Cleanup"
#!/bin/bash

# Do not use errexit here: an unmounted path is an expected shutdown state.
set -u -o pipefail

MOUNT_ITEMS=($MOUNT_ITEMS)

cleanup_mounts() {
    local item name share mount_point

    for item in "\${MOUNT_ITEMS[@]}"; do
        IFS="|" read -r name share mount_point <<< "\$item"
        [[ -n "\$mount_point" ]] || continue

        # Do not probe CIFS mounts here: those checks can block during shutdown.
        umount -l -- "\$mount_point" >/dev/null 2>&1 || true
    done
}

cleanup_mounts
EOL
chmod +x "$Cleanup"

cat <<EOL > "$HELPER"
#!/bin/bash

# --- 配置区 ---
NAS="hfs.minieye.tech"
CRED="/etc/creds/nas.cred"
CLEANUP="$Cleanup"
MOUNT_ITEMS=($MOUNT_ITEMS)

# noserverino: inode 编号由本地生成，提高兼容性和响应速度
# echo_interval=5: 每5秒发送一次SMB心跳，更快发现断连。
# actimeo=15: 缩短属性缓存时间，避免看到已不存在的假文件。
# timeo=20: 断连时等待时间。
# retrans=2: 重传 2 次后放弃。
# rsize/wsize: 针对不稳定网络，适当限制单次传输块大小（可选）。
MOUNT_OPTS="credentials=\$CRED,uid=1000,iocharset=utf8,vers=3.0,soft,actimeo=15"

# 容错控制
FLAG=1
FAIL_COUNT=0
MAX_FAILURES=3  # 连续失败3次才判定为彻底断开
CHECK_INTERVAL=5 # 检查间隔（秒）

mount_share() {
    local name="\$1"
    local share="\$2"
    local mount_point="\$3"

    grep -qs " \$mount_point " /proc/mounts
    local mounted=\$?

    if (( mounted != 0 )); then
        echo "✅ 已连上内网，尝试挂载 \$name: \$share -> \$mount_point"
        mkdir -p "\$mount_point"
        mount -t cifs "\$share" "\$mount_point" -o "\$MOUNT_OPTS"
    else
        (( FLAG == 1)) && echo "✅ \$name 已挂载，状态正常。"
        (( FLAG == 2)) && echo "✅ 网络重连成功，\$name 状态正常。"
    fi
}

cleanup() {
    "\$CLEANUP" || echo "⚠️ NAS cleanup reported an error." >&2
}

# Exit cleanly after releasing mounts when systemd sends its normal stop
# signal; Restart=on-failure below therefore will not restart this exit.
stopping=0
stop_and_cleanup() {
    # Ignore repeated stop signals while cleanup is in progress.
    (( stopping )) && exit 0
    stopping=1
    trap '' TERM INT
    cleanup
    exit 0
}
trap 'stop_and_cleanup' TERM INT

while true; do
    ONLINE=1 # 默认离线
    # 尝试 Ping，并探测端口
    if ping -c 2 -W 3 "\$NAS" >/dev/null 2>&1 || timeout 2 bash -c "</dev/tcp/\$NAS/445" >/dev/null 2>&1; then
        ONLINE=0 # 在线
    fi

    if (( ONLINE == 0 )); then
        # 网络正常
        FAIL_COUNT=0
        for item in "\${MOUNT_ITEMS[@]}"; do
            IFS="|" read -r name share mount_point <<< "\$item"
            mount_share "\$name" "\$share" "\$mount_point"
        done
        FLAG=0
    else
        ((FAIL_COUNT++))
        if (( FAIL_COUNT >= MAX_FAILURES )); then
            if (( FLAG != 1 )); then
                echo "❌ 连续 \$FAIL_COUNT 次重连失败，请检查网络状态，正在卸载 NAS..."
                cleanup
            fi
            FLAG=1
        else
            has_mount=0
            for item in "\${MOUNT_ITEMS[@]}"; do
                IFS="|" read -r name share mount_point <<< "\$item"
                if grep -qs " \$mount_point " /proc/mounts; then
                    has_mount=1
                    break
                fi
            done
            if (( has_mount == 1 )); then
                echo "⚠️ 探测到网络抖动，正在尝试重连(\$FAIL_COUNT/\$MAX_FAILURES)"
                FLAG=2
            else
                echo "❌ 网络离线中，Nas 未挂载。"
            fi
        fi
    fi
    sleep "\$CHECK_INTERVAL"
done
EOL
chmod +x "$HELPER"

# The helper owns shutdown cleanup so systemd signals it before any remount work.
# 创建 Systemd 服务
cat <<EOL > /etc/systemd/system/nasmount.service
[Unit]
Description=NAS Auto Mount Guardian
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=$HELPER
TimeoutStopSec=10s
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOL

# 启动服务
systemctl daemon-reload
systemctl enable --now nasmount
echo "------------------------------------------------"
echo -e "${G}✅ NAS 自动挂载服务已部署！${NC}"
echo -e "💡 挂载点: ${B}$MOUNT_POINTS${NC}"
echo -e "💡 监控日志: ${G}journalctl -u nasmount -f${NC}"
echo
echo "💡 日常管理:"
echo "   sudo systemctl status nasmount         # 查看服务状态"
echo "   sudo systemctl start nasmount          # 启动服务"
echo "   sudo systemctl stop nasmount           # 停止服务"
echo "   sudo systemctl restart nasmount        # 重启服务"
echo "   sudo systemctl disable nasmount        # 停止开机自启"
echo "   sudo systemctl enable --now nasmount   # 立即启用并开机自启"
echo "------------------------------------------------"
echo -e "✅ 正在挂载 Nas，稍候查看日志确认状态..."
sleep 4
journalctl -u nasmount -f
