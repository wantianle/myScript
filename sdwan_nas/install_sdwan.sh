#!/bin/bash

# 颜色
G='\033[0;32m'  # 绿
R='\033[0;31m'  # 红
Y='\033[0;33m'  # 黄
B='\e[0;34m'  # 蓝
NC='\033[0m'    # 重置

# 检查 root 权限
if [[ $EUID -ne 0 ]]; then
   echo "❌ 错误: 必须使用 root 权限运行此脚本 (请使用 sudo)"
   exit 1
fi

nodes=(
    "1|电信专线 [1000M]|(推荐使用)|minieye.9966.org"
    "2|电信普宽 [3*100M]|(L4部门优先)|dwan.minieye.tech"
    "3|移动专线 [500M]||minieye.8866.org"
    "4|联通普宽 [200M]|(仅限联通用户)|minieye.2288.org"
    "5|电信专线 [50M]|(财务专用)|youjia.8866.org"
)
echo "---------- ⚡ 开始部署公司内网连接服务 ----------"
echo "正在检测服务器延迟..."
cache=""
for node in "${nodes[@]}"; do
    IFS="|" read -r id name tag addr <<< "$node"
    avg_latency=$(ping -c 2 -W 2 "$addr" 2>/dev/null | awk -F '/' 'END {print $5}')
    if [ -z "$avg_latency" ]; then
        display_lat="[Timeout ❌]"
        lat_color="$R"
    else
        lat_int=$(printf "%.0f" "$avg_latency")
        if (( "$lat_int" <= 100 )); then
            lat_color="$G"
        elif (( "$lat_int" <= 300 )); then
            lat_color="$Y"
        else
            lat_color="$R"
        fi
        display_lat="[${avg_latency}ms]"
    fi
    line="${id}) | ${name} | ${tag} | ${B}${addr}${NC} | ${lat_color}${display_lat}${NC}"
    cache="${cache}${line}\n"
done
echo -e "$cache" | column -t -s "|"
echo "--------------------------------------"
echo -e "${B}请选择接入服务器 (直接回车默认选 1):${NC}"
read choice
case $choice in
    2) SERVER="dwan.minieye.tech" ;;
    3) SERVER="minieye.8866.org" ;;
    4) SERVER="minieye.2288.org" ;;
    5) SERVER="youjia.8866.org" ;;
    *) SERVER="minieye.9966.org" ;;
esac
echo -e "${G}✅ 已选择服务器: ${SERVER}${NC}"

CONFIG_DIR="/etc/sdwan"
CONFIG_FILE="$CONFIG_DIR/iwan.conf"
reconfig=""
if [[ -f "$CONFIG_FILE" ]]; then
    while [[ ! "$reconfig" =~ ^[yYnN]$ ]]; do
        read -p "发现已存在配置文件 $CONFIG_FILE，是否重新配置? (y/n/v查看): " choice
        if [[ "$choice" == "v" ]]; then
            echo -e "${B}🔐 当前配置:${NC}"
            cat "$CONFIG_FILE"
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
    read -p "👤 请输入工号 (username): " username
    read -sp "🔑 请输入 SDWAN 密码 (password): " password
    echo
    mkdir -p "$CONFIG_DIR"
    cat <<EOL > "$CONFIG_FILE"
[iwan1]
server=$SERVER
username=$username
password=$password
port=10010
mtu=1436
encrypt=0
pipeid=0
pipeidx=0
EOL
    chmod 600 "$CONFIG_FILE"
    echo -e "${G}✅ 配置文件已生成${NC}"
else
    echo -e "${G}✅ 保留现有配置${NC}"
fi

# 部署核心程序
SDWAN_BIN="./sdwand"
TARGET_BIN="/usr/local/bin/sdwand"

if [ -f "$SDWAN_BIN" ]; then
    echo -e "${G}✅ 部署 sdwand 程序到 $TARGET_BIN...${NC}"
    cp "$SDWAN_BIN" "$TARGET_BIN"
    chmod a+x "$TARGET_BIN"
else
    if [ ! -f "$TARGET_BIN" ]; then
        echo -e "${R}❌ 错误: 当前目录下未找到 sdwand 文件。${NC}"
        exit 1
    fi
fi
# 创建启动脚本
HELPER_SCRIPT="/usr/local/bin/sdwan_helper.sh"
echo "🚀 创建启动脚本..."

cat <<'EOL' > "$HELPER_SCRIPT"
#!/bin/bash

# 当收到 Systemd 的停止信号时，同时关闭主程序
cleanup() {
    echo "停止服务中，正在清理进程和路由..."
    kill $SDWAN_PID 2>/dev/null
    ip route del 192.168.0.0/16 dev iwan1 2>/dev/null
    exit 0
}
# 捕获退出信号
trap cleanup SIGTERM SIGINT
# 清理防止旧路由冲突
ip route del 192.168.0.0/16 2>/dev/null

echo "🚀 正在启动 sdwand 主程序..."
/usr/local/bin/sdwand &
SDWAN_PID=$!

add_sdwan_route() {
    if ! ip route show 192.168.0.0/16 | grep -q iwan1; then
        if ip route add 192.168.0.0/16 dev iwan1 metric 10 2>/dev/null; then
            echo "✅ 路由已添加/恢复"
            return 0
        fi
    fi
    return 1
}

echo "⚠️ 等待 iwan1 接口完全就绪 (UP/UNKNOWN)..."
sleep 3
for i in {1..5}; do
    sleep 2
    if add_sdwan_route; then break; fi
done

echo "🛡️ 路由守卫已激活，正在监控链路状态..."
while kill -0 $SDWAN_PID 2>/dev/null; do
    if ip link show iwan1 2>/dev/null | grep -q "DOWN"; then
        echo "⚠️ 网卡启动失败，请尝试手动重启：sudo ip link set iwan1"
        continue
    fi
    add_sdwan_route
    sleep 10
done

wait $SDWAN_PID
EOL

chmod +x "$HELPER_SCRIPT"

# 配置 Systemd 守护进程
SERVICE_FILE="/etc/systemd/system/sdwan.service"
echo "🚀 配置 Systemd 守护进程..."

cat <<EOL > "$SERVICE_FILE"
[Unit]
Description=Company SD-WAN Auto-Connect Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=$HELPER_SCRIPT
Restart=always
RestartSec=10
KillMode=control-group
KillSignal=SIGTERM
ExecStopPost=/usr/bin/pkill -9 sdwand

[Install]
WantedBy=multi-user.target
EOL

# 加载并启动，状态自检
echo "🚀 正在激活 systemd 服务并验证服务状态..."
echo "------------------------------------------------"
systemctl daemon-reload
systemctl enable --now sdwan
sleep 2

# 检查 Systemd 服务
if systemctl is-active --quiet sdwan; then
    echo -e "✅ 服务状态: ${G}运行中 (Running)${NC}"
else
    echo -e "❌ 服务状态: ${R}未启动 (Error)，请检查日志获取更多信息: sudo journalctl -u sdwan -f -n 20${NC}"
    journalctl -u sdwan --no-pager | tail -n 5
fi

# 检查网卡
sleep 2
if ip link show iwan1 &> /dev/null; then
    echo -e "   虚拟网卡: ${G}iwan1 已创建${NC}"
    ip addr show iwan1 | grep "inet " | awk '{print "   └─ 分配 IP: " $2}'
else
    echo -e "   虚拟网卡: ${Y}iwan1 未找到 (可能连接中，请稍后查看)${NC}"
fi
sleep 2
# 检查静态 ip 冲突
CURRENT_IP=$(ip route get 8.8.8.8 2>/dev/null | grep -oP 'src \K\S+')
if [[ $CURRENT_IP =~ ^192\.168\.2\. ]]; then
    echo -e "❌ ${R}当前 IP 为 $CURRENT_IP，网段与公司内网冲突，请更换网段...${NC}"
fi
sleep 2
# 检查路由
ROUTE_CHECK=$(ip route | grep iwan1)
if [ -n "$ROUTE_CHECK" ]; then
    echo -e "   静态路由: ${G}已自动添加${NC}"
    echo "$ROUTE_CHECK" | sed 's/^/       │ /' | sed '$s/│/└─/'
else
    echo -e "   静态路由: ${Y}未发现路由记录，请稍候查看${NC}"
fi
echo -e "${G}✅ 部署完成！你可以通过以下命令管理 SD-WAN 服务：${NC}"
sleep 1
echo
echo -e "${G}💡 查看状态:${NC}"
echo "   ping hfs.minieye.tech               # 查看网络连通状态"
echo "   sudo systemctl status sdwan         # 查看服务状态"
echo "   ip link show dev iwan1              # 查看虚拟网卡状态"
echo "   ip route | grep iwan1               # 查看静态路由"
echo "   sudo journalctl -u sdwan -f -n 20   # 查看服务日志"
echo
echo -e "${G}💡 日常管理:${NC}"
echo "   sudo systemctl disable sdwan        # 停止开机自启"
echo "   sudo systemctl enable --now sdwan   # 立即启用并开机自启"
echo "   sudo systemctl start sdwan          # 启动服务"
echo "   sudo systemctl stop sdwan           # 停止服务"
echo "   sudo systemctl restart sdwan        # 重启服务"
echo
echo -e "${Y}❗ 彻底卸载: 请运行 uninstall_sdwan.sh${NC}"
