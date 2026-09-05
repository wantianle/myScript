#!/usr/bin/env bash

#region ==================== HEADER ====================

# 颜色配置
RED='\033[1;31m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
NC='\033[0m'
# 免密配置
SUDO_PATH="/etc/sudoers.d/mdrive_perms"
KEY_PATH="$HOME/.ssh/id_ed25519"
CONFIG_PATH="$HOME/.ssh/config"
# 路径配置
DISK_LABEL="data"
MOUNT_ROOT="/media/data"
CONF_DIR_SOC1="/mdrive/mdrive_conf/supervisor/soc1/conf"
CONF_DIR_SOC2="/mdrive/mdrive_conf/supervisor/soc2/conf"
# 网络配置
PC_USER="mini"
SOC2_IP="192.168.10.3"
SSH_OPTS="-o ConnectTimeout=2 -o ServerAliveInterval=2 -o ServerAliveCountMax=2"
SERVER_IP="ad.minieye.tech"
INTERNAL_DEVICES=(
    "192.168.20.10:AT128P_Right"
    "192.168.20.20:AT128P_Front"
    "192.168.20.30:AT128P_Left"
    "192.168.20.15:Airy_Right"
    "192.168.20.35:Airy_Left"
    "192.168.20.45:Airy_Back"
    "192.168.21.10:GNSS/INS"
    "172.168.16.100:MCU"
    "192.168.10.21:OBU"
    "192.168.10.22:RearScreen"
)
# 包配置
REMOTE_CONFIG="$HOME/.md_remotes"
packages=(
        "mdrive:mdrive"
        "mdrive_conf:mdrive_conf|conf"
        "mdrive_map:mdrive_map|map"
        "mdrive_dep:mdrive_dep|dep"
        "mdrive_model:mdrive_model|model"
)

#endregion

#region ===================== UTILS ======================

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok()  { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_err() { echo -e "${RED}[ERROR]${NC} $1"; }


usage() {
    if [[ "$INSIDE_MD" == "true" ]]; then
        local prefix=""
    else
        local prefix="md "
    fi
    echo -e "${BLUE}Usage:${NC}"
    echo -e "  $prefix<c(command)> [a(arguments)] <>代表必选 []代表可选 ()代表可简写"
    echo -e "${BLUE}Commands:${NC}"
    printf "  ${YELLOW}%-45s${NC}  ${YELLOW}%s${NC}\n" "init"            "每次部署工具需要初始化免密并安装工具到系统"
    printf "  %-45s  %s\n" "check"                                       "检查车辆状态"
    printf "  %-45s  %s\n" "umount"                                      "安全弹出硬盘"
    printf "  %-45s  %s\n" "upgrade"                                     "自检并升级最新包版本"
    printf "  %-45s  %s\n" "install [version]"                           "手动升级多个组件版本，也可通过参数升级单个组件版本"
    printf "  %-45s  %s\n" "rb(rollback) [version_keyword]"              "根据 remote 文件或指定关键字回滚升级任意版本的包"
    printf "  %-45s  %s\n" "stop/start/restart/status [1(soc1)|2(soc2)]" "同时管理 soc1&2 服务，也可以通过参数指定单端"
    printf "  %-45s  %s\n" "log <1(soc1)|2(soc)>"                        "查看 5 分钟内 soc1/soc2 服务日志"
    printf "  %-45s  %s\n" "c(channel) [1(soc1)|2(soc2)]"                "查看 soc1/soc2 channel 消息"
    printf "  %-45s  %s\n" "m(module)"                                   "管理 soc1&2 模块，查看对应模块日志和开发日志"
    printf "  %-45s  %s\n" "record [on]|<off>"                           "开启关闭 soc1&2 的Recorder和TestTool"
    printf "  %-45s  %s\n" "e(export)"                                   "交互式选择需要导出的 bag/log 文件或文件夹"
    printf "  %-45s  %s\n" "remote <add|del|list>"                       "管理本地包对应的远程分支"
    printf "  %-45s  %s\n" ""                                            "  remote add <name> [branch|'-'] [platform]"
    printf "  %-45s  %s\n" ""                                            "  remote del <name>"

    # printf "  %-45s | %s\n" "push <src> [dst]"          "推送文件到宿主机 (默认 $DEST_ROOT)"
    # printf "  %-45s | %s\n" "pull <src> [dst]"          "从宿主机拉取文件到指定路径 (默认 $DEST_ROOT)"
    echo ""
}

#endregion

#region ==================== MODULES =====================

#region -------------------  sys 系统层 ------------------

# 免密处理
sys::nopasswd(){
    # 免密ssh
    if [ ! -f "$KEY_PATH" ]; then
        echo "未发现密钥，正在生成默认密钥..."
        ssh-keygen -t ed25519 -f "$KEY_PATH" -N ""
        echo "推送公钥到soc2：$USER@$SOC2_IP..."
        ssh-copy-id -i "${KEY_PATH}.pub" "$USER@$SOC2_IP"
    fi
    if ! grep -q "Host soc2" "$CONFIG_PATH"; then
        echo "配置 soc2 快捷登录：ssh soc2"
        cat << EOF >> "$CONFIG_PATH"
# Orin SOC2 快捷登录
Host soc2
    HostName $SOC2_IP
    User $USER
EOF
        chmod 600 "$CONFIG_PATH"
    fi
    # 免密sudo
    if [[ ! -f $SUDO_PATH ]]; then
        echo "配置 soc1 免密 sudo..."
        echo 'nvidia ALL=(ALL) NOPASSWD: ALL' | sudo tee "$SUDO_PATH"
        sudo chmod 0440 "$SUDO_PATH"
        echo "配置 soc2 免密 sudo..."
        ssh $SSH_OPTS -t "$SOC2_IP" "echo 'nvidia ALL=(ALL) NOPASSWD: ALL' | sudo tee $SUDO_PATH"
        ssh $SSH_OPTS "$SOC2_IP" "sudo chmod 0440 $SUDO_PATH"
    fi
}


# 初始化命令行工具
sys::init(){
    # 安装二进制命令
    if sudo cp "$HOME"/md.sh /usr/local/bin/md &>/dev/null && sudo chmod +x /usr/local/bin/md; then
        log_ok "工具已安装到 /usr/local/bin/md"
    else
        log_err "初始化失败，请检查 $HOME/md.sh 是否存在！"
        return 1
    fi

    # 安装自动补全脚本
    local completion_file="/etc/bash_completion.d/md"
    echo "正在安装自动补全..."
    sudo bash -c "cat << 'EOF' > $completion_file
$(declare -f _md_completions)
complete -F _md_completions md
EOF"

    log_ok "初始化完成！请执行 'source $completion_file' 或重启终端生效。"
    echo -e "试试输入: ${GREEN}md [TAB][TAB]${NC}"
}


sys::date(){
    echo -n "[soc1]date: "
    date
    echo -n "[soc2]date: "
    ssh $SSH_OPTS "$SOC2_IP" "date"
}


# 清理内盘数据
sys::clean(){
    local avail
    avail=$(df -BG $MDRIVE_CACHE | awk 'NR==2 {print $4}' | tr -d 'G')
    if [[ "$avail" -lt 5 ]]; then
        log_warn "系统剩余空间不足 5GB (当前: ${avail}GB)，过低会影响 OTA 版本升级，是否需要清理？(Y/n)"
        read -r confirm
        [[ "$confirm" == "n" || "$confirm" == "N" ]] && return
        log_info "正在清理缓存：$MDRIVE_CACHE "
        sudo rm -rf $MDRIVE_CACHE/data/*
    fi
}


sys::export() {
    local timestamp=$(date +%m%d_%H%M)
    local local_dest="/media/mdrive_export/${timestamp}"
    local ssh_port=22
    local local_ip=""

    # 检查是否存在反向隧道 (监听在车端本地的 2222 端口)
    if netstat -tuln | grep -q ":2222"; then
        log_info "检测到 SSH 反向隧道，启用公网回传模式..."
        local_ip="127.0.0.1"
        ssh_port=2222
    else
        local_ip=$(echo "$SSH_CONNECTION" | awk '{print $1}' | tr -d '\r')
        log_info "走局域网直连模式 (Target: $local_ip)..."
    fi

    if [[ -z "$local_ip" ]]; then
        log_err "未检测到本地 SSH 连接 IP"
        return 1
    fi

    ssh_opts=( -p "$ssh_port" -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=2 -o LogLevel=ERROR )
    ssh_copy_opts=( -p "$ssh_port" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=2 -o LogLevel=ERROR )

    if ! ssh -q "${ssh_opts[@]}" "$PC_USER@$local_ip" exit 2>/dev/null; then
        log_info "未检测到免密授权，准备配置 (Target: $PC_USER@$local_ip:$ssh_port)..."
        if ssh-copy-id "${ssh_copy_opts[@]}" "$PC_USER@$local_ip"; then
            log_ok "免密验证通过！"
            if ! ssh -q "${ssh_opts[@]}" "$PC_USER@$local_ip" exit 2>/dev/null; then
                log_err "公钥已下发，但免密验证仍失败，请检查目标端 authorized_keys 与 SSH 配置"
                return 1
            fi
        else
            log_err "免密配置未生效（可能是密码错误、目标用户不匹配，或笔记本 SSH 未开启）"
            return 1
        fi
    fi

    # 2. 文件扫描与交互选择
    log_info "正在扫描 $MDRIVE_DATA_ROOT/{bag,log,core,pcap,crash_log,perf} 目录..."

    local selections
    selections=$(cd -L "$MDRIVE_DATA_ROOT" && find -L -maxdepth 3 -not -path '*/.*' 2>/dev/null | sort | fzf \
        --multi \
        --ansi \
        --layout=reverse \
        --height=95% \
        --header "模式: $([[ $ssh_port == 2222 ]] && echo "公网隧道" || echo "局域网") | Tab:勾选 | Ctrl-A:全选 | Enter:确认并导出" \
        --bind "ctrl-a:toggle-all")

    [[ -z "$selections" ]] && { log_warn "已取消操作"; return; }

    local count=$(echo "$selections" | wc -l)
    log_info "开始传输 $count 项内容到 $local_dest"

    ssh "${ssh_opts[@]}" "$PC_USER@$local_ip" "mkdir -p $local_dest"

    cd $MDRIVE_DATA_ROOT

    while IFS= read -r item; do
        [[ -z "$item" ]] && continue
        rsync -avPL -R -e "ssh ${ssh_opts[*]}" "$item" "$PC_USER@$local_ip:$local_dest/"
        if [[ $? -ne 0 ]]; then
            log_err "传输中断: $item"
        fi
    done <<< "$selections"

    log_ok "导出完成！本地路径: $local_ip:$local_dest"
}

#endregion

#region -------------------  svc 服务层 ------------------

# 查看服务运行标识
svc::check() {
    case "$1" in
        "soc1")
            if systemctl is-active --quiet mdrive.service; then
                echo -e "[soc1]服务状态: ${GREEN}Running${NC}"
            else
                echo -e "[soc1]服务状态: ${RED}Stopped or Failed${NC}"
            fi
            ;;
        "soc2")
            ssh $SSH_OPTS "$SOC2_IP" "systemctl is-active --quiet mdrive.service"
            local status=$?
            if [[ $status -eq 0 ]]; then
                echo -e "[soc2]服务状态: ${GREEN}Running${NC}"
            elif [[ $status -ne 255 ]]; then
                echo -e "[soc2]服务状态: ${RED}Stopped or Failed${NC}"
            fi
            ;;
    esac
}


# 管理服务
svc::manage(){
    local action=$1
    case "$2" in
        "soc1")
            log_info "$action soc1 mdrive service..."
            sudo systemctl $action mdrive.service
            svc::check soc1
            ;;
        "soc2")
            log_info "$action soc2 mdrive service..."
            ssh $SSH_OPTS "$SOC2_IP" "timeout 15 sudo systemctl $action mdrive.service"
            svc::check soc2
            ;;
    esac

}

# 查看日志
svc::log(){
    case "$1" in
        "soc1"|"1"|"")
            sudo journalctl -eu mdrive.service --since "5 min ago" -f --no-pager | grep --line-buffered -v -E "ptp4l|phc2sys"
            ;;
        "soc2"|"2")
            ssh $SSH_OPTS -t "$SOC2_IP" 'sudo journalctl -eu mdrive.service --since "5 min ago" -f --no-pager | grep --line-buffered -v -E "ptp4l|phc2sys"'
            ;;
    esac
}


# recorder
svc::recorder(){
    disk::check
    local avail
    avail=$(df -BG "$MOUNT_ROOT" | awk 'NR==2 {print $4}' | tr -d 'G')
    if [[ "$avail" -lt 200 ]]; then
        log_warn "数据盘剩余空间不足 200GB (当前: ${avail}GB)！"
    fi
    if [[ $1 == "on" || $1 == "" ]]; then
        sudo supervisorctl start Recorder
        sudo supervisorctl start TestTool
        ssh $SSH_OPTS "$SOC2_IP" "sudo supervisorctl start Recorder"
    elif [[ $1 == "off" ]]; then
        sudo supervisorctl stop Recorder
        sudo supervisorctl stop TestTool
        ssh $SSH_OPTS "$SOC2_IP" "sudo supervisorctl stop Recorder"
    else
        usage
    fi
}


svc::channel(){
    case "$1" in
        "soc1"|"1"|"")
            cyber_monitor
            ;;
        "soc2"|"2")
            ssh $SSH_OPTS -t "$SOC2_IP" "export MDRIVE_ROOT_DIR='/mdrive' && export MDRIVE_DEP_DIR='/mdrive/mdrive_dep' && source $VMC_SOFTWARE/mdrive/setup.sh && cyber_monitor"
            ;;
    esac
}

# 模块动作执行器
# 用法: svc::mod_handler "<fzf_line>" <action>
svc::mod_handler() {
    local line="$1"
    local action="$2"
    local clean_line soc mod
    clean_line="${line//$'\x1b'\\[[0-9;]*m/}"
    soc=$(echo "$clean_line" | awk '{print $1}' | tr -d '[]')
    mod=$(echo "$clean_line" | awk '{print $2}')
    [[ -z "$soc" || -z "$mod" ]] && return

    case "$action" in
        "glog"|"sv")
            local path
            path=$(log_get_path "$soc" "$mod" "$action")
            if [[ "$action" == "glog" ]]; then
                local exists=false
                if [[ -L "$path" ]]; then
                    exists=true
                fi
                if [[ "$exists" == "false" ]]; then
                    echo -e "${YELLOW}未匹配到精准日志，请手动选择:${NC}"
                    local list_cmd="find $GLOG_log_dir -maxdepth 1 -type l -name '*.INFO*' -printf '%f\n'"
                    local picked
                    picked=$(eval "$list_cmd" | sort | fzf \
                        --height=100% \
                        --layout=reverse \
                        --border \
                        --header "--- 日志列表 ---" \
                        --info=inline)
                    [[ -z "$picked" ]] && return
                    path="$GLOG_log_dir/$picked"
                fi
            fi
            sudo less -R -S --follow-name +F "$path"
            ;;
        "start"|"stop"|"restart")
            echo -e "正在对 [$soc] $mod 执行 $action..."
            if [[ "$soc" == "soc1" ]]; then
                sudo supervisorctl "$action" "$mod"
            else
                ssh $SSH_OPTS "$SOC2_IP" "sudo supervisorctl $action $mod"
            fi
            sleep 1
            ;;
    esac
}


# 智能搜索日志文件路径
log_get_path() {
    local soc=$1
    local mod=$2
    local type=$3
    local conf_dir=$CONF_DIR_SOC1
    [[ $soc == "soc2" ]] && conf_dir=$CONF_DIR_SOC2

    local conf_file=$conf_dir/$mod.conf
    set -- "$conf_file"
    [[ -f "$1" ]] && conf_file="$1"
    [[ -z $conf_file ]] && return
    local raw_cmd=""
    local sv_log=""
    while read -r line || [[ -n $line ]]; do
        if [[ $line =~ ^stdout_logfile= ]]; then
            sv_log="${line#*=}"
            sv_log="${sv_log%%;*}"
            sv_log="${sv_log//[[:space:]]/}"
        elif [[ $line =~ /mdrive/bin ]]; then
            raw_cmd="$line"
        fi
    done < "$conf_file"

    if [[ $type == "sv" ]]; then
        # 情况 A: SV 日志直接返回
        echo $sv_log
    else
        # 情况 B: Glog 探测
        local bin_name
        local bin_path
        bin_path=$(echo "$raw_cmd" | grep -oP '/mdrive/bin/[^ ]+')
        bin_name="${bin_path##*/}"
        bin_name="${mod,,}"
        local base_name="${bin_name#mdrive_}"
        local mod_lower="${mod,,}"
        local mod_clean="${mod_lower#mdrive_}"

        # 按优先级探测软链接 (.INFO)
        # 优先级顺序：二进制名 > 去掉前缀名 > 小写模块名 > 小写模块去掉前缀名
        local candidates=(
            "${bin_name}.INFO"
            "${base_name}.INFO"
            "${mod_lower}.INFO"
            "${mod_clean}.INFO"
        )
        for c in "${candidates[@]}"; do
            if [[ -L "$GLOG_log_dir/$c" ]]; then
                echo "$GLOG_log_dir/$c"
                return
            fi
        done
    fi
}


# 获取并格式化双端状态
fetch_combined() {
    local s1 s2
    s1=$(sudo supervisorctl status | awk '{print "soc1 " $0}')
    s2=$(ssh $SSH_OPTS "$SOC2_IP" "sudo supervisorctl status" 2>/dev/null | awk '{print "soc2 " $0}')
    printf "%s\n" "$s1" "$s2" | while read -r line; do
        local clean_line soc mod state tail
        clean_line=$(echo "$line" | tr -s ' ')
        read -r soc mod state tail <<< "$clean_line"
        if [[ "$state" == "RUNNING" ]]; then
            if echo "$tail" | grep -q "uptime 0:00:0"; then
                printf "${YELLOW}[%-4s] %-45s %-8s %s${NC}\n" "$soc" "$mod" "$state" "$tail"
            else
                printf "${GREEN}[%-4s] %-45s %-8s %s${NC}\n" "$soc" "$mod" "$state" "$tail"
            fi
        else
            printf "${RED}[%-4s] %-45s %-8s %s${NC}\n" "$soc" "$mod" "$state" "$tail"
        fi
    done
}
export -f fetch_combined svc::mod_handler log_get_path
export CONF_DIR_SOC1 CONF_DIR_SOC2 SSH_OPTS SOC2_IP RED GREEN YELLOW BLUE NC

svc::module() {
    if ! command -v fzf &> /dev/null; then
        log_warn "请先安装 fzf..."
        return 1
    fi
    fetch_combined | fzf \
        --ansi \
        --height 95% \
        --reverse \
        --header "操作: Enter:模块日志 | Alt-Enter:开发日志 | Alt-S:启动 | Alt-X:停止 | Alt-R:重启 | Ctrl-R:刷新" \
        --bind "enter:execute(svc::mod_handler {} sv)" \
        --bind "alt-enter:execute(svc::mod_handler {} glog)" \
        --bind "alt-s:execute(svc::mod_handler {} start)+reload(fetch_combined)" \
        --bind "alt-x:execute(svc::mod_handler {} stop)+reload(fetch_combined)" \
        --bind "alt-r:execute(svc::mod_handler {} restart)+reload(fetch_combined)" \
        --bind "ctrl-r:reload(fetch_combined)" \
        --bind "esc:abort"
}

#endregion

#region ------------------- disk 硬盘层 ------------------

# 获取当前设备路径
disk::_get_dev() {
    blkid -L "$DISK_LABEL" | tail -n 1
}

disk::_get_mnt_dev() {
    findmnt -n -o SOURCE "$MOUNT_ROOT"
}

# 检查硬盘是否正确挂载双端
disk::check(){
    if [[ $MDRIVE_VEHICLE_MODEL == "ECAR_HW4" ]]; then
        # 适配物流车逻辑
        if mountpoint -q $MOUNT_ROOT; then
            echo -e "[soc1]硬盘: ${GREEN}Mounted${NC}"
        else
            echo -e "[soc1]硬盘: ${RED}Umounted${NC}"
        fi
    else
        local dev mnt
        dev=$(disk::_get_dev)
        mnt=$(disk::_get_mnt_dev)
        if [[ -n "$dev" && "$mnt" == "$dev" ]]; then
            echo -e "[soc1]硬盘: ${GREEN}Mounted${NC}"
        else
            echo -e "[soc1]硬盘: ${RED}Umounted${NC}"
        fi
    fi
    if ssh $SSH_OPTS "$SOC2_IP" "timeout 2 mountpoint -q $MOUNT_ROOT"; then
        echo -e "[soc2]硬盘: ${GREEN}Mounted${NC}"
    else
        echo -e "[soc2]硬盘: ${RED}Umounted or Error${NC}"
    fi
}


disk::usage() {
    local name=$1
    local path=$2
    local disk_usage
    disk_usage=$(df -h "$path" | awk 'NR==2 {print $5}' | tr -d '%')
    printf "%-41s" "[硬盘] $name:"
    if [[ ! "$disk_usage" =~ ^[0-9]+$ ]]; then
            log_err "读取失败"
            return 2
    fi
    if [[ "$disk_usage" -lt 85 ]]; then
        echo -e "${GREEN}正常 (${disk_usage}%)${NC}"
        return 0
    else
        log_err "空间不足! (${disk_usage}%)"
        check_pass=false
        return 1
    fi
}


# 安全卸载
disk::umount(){
    sync && sync
    while mountpoint -q $MOUNT_ROOT; do
        sudo umount -l $MOUNT_ROOT 2>/dev/null
    done
    ssh $SSH_OPTS $SOC2_IP "sudo umount -l $MOUNT_ROOT 2>/dev/null"
    log_ok "硬盘卸载成功..."
}


disk::diagnose(){
    # return 1 无硬盘 2 未挂载 3 挂载残留 4 挂载点访问超时 5 I/O错误（盘满或损坏）6 软链接路径指向错误 7 内盘空间不足
    local dev mnt
    dev=$(disk::_get_dev)
    mnt=$(disk::_get_mnt_dev)
    if [[ -z "$dev" ]]; then
        log_err "硬盘未识别 $DISK_LABEL"
        return 1
    fi

    if ! mountpoint -q $MOUNT_ROOT; then
        log_err "硬盘未挂载 soc1:$MOUNT_ROOT"
        return 2
    fi

    ssh $SSH_OPTS "$SOC2_IP" "mountpoint -q $MOUNT_ROOT"
    local res=$?
    if [[ ! $res =~ ^(0|130|255)$ ]]; then
        log_err "硬盘未挂载 soc2:$MOUNT_ROOT"
        return 2
    fi

    if [[ $mnt != "$dev" ]]; then
        log_err "挂载目录被占用 $mnt"
        return 3
    fi

    if ! timeout 2 stat -t "$MOUNT_ROOT/data" >/dev/null 2>&1; then
        log_err "挂载目录内容无法访问 $MOUNT_ROOT"
        return 4
    fi

    if ! ssh $SSH_OPTS "$SOC2_IP" "timeout 2 stat -t $MOUNT_ROOT/data >/dev/null 2>&1"; then
        log_err "挂载目录内容无法访问 $MOUNT_ROOT"
        return 4
    fi

    if grep "$MOUNT_ROOT" /proc/mounts | grep -q " ro,"; then
        log_err "文件系统已降级为 [只读] soc1:${MOUNT_ROOT}"
        return 5
    fi

    if ssh $SSH_OPTS "$SOC2_IP" "grep $MOUNT_ROOT /proc/mounts | grep -q ' ro,'"; then
        log_err "文件系统已降级为 [只读] soc2:${MOUNT_ROOT}"
        return 5
    fi

    local path
    path=$(readlink -f $MDRIVE_DATA_ROOT)
    if [[ $path != "$MOUNT_ROOT/data" ]]; then
        log_warn "路径链接指向错误 $MDRIVE_DATA_ROOT -> $path"
        return 6
    fi

    local avail
    avail=$(df -BG "$MDRIVE_CACHE" | awk 'NR==2 {print $4}' | tr -d 'G')
    if [[ "$avail" -lt 5 ]]; then
        log_warn "$MDRIVE_CACHE 剩余空间不足 5GB (当前: ${avail}GB)，过低会影响 OTA 版本升级"
        return 7
    fi

    return 0
}


# 修复硬盘损坏
disk::fix(){
    # return 1 无硬盘 2 未挂载 3 挂载残留 4 挂载点访问超时 5 I/O错误（盘满或损坏）6 软链接路径指向错误 7 内盘空间不足
    local dev
    dev=$(disk::_get_dev)
    local err_code=$1
    svc::manage stop soc1
    svc::manage stop soc2
    log_info "开始执行修复程序 (Error Code: $err_code)..."
    case "$err_code" in
        "1")
        log_warn "检查并重启电源：1.硬盘是否插好 2.盘符是否为 data 3.硬盘/硬盘线可能损坏 "
        return 1
        ;;
        "2"|"3")
        disk::umount
        sudo mount $dev $MOUNT_ROOT
        ssh $SSH_OPTS "$SOC2_IP" "sudo systemctl restart media-data.mount"
        log_ok "挂载清理完成！"
        ;;
        "4"|"5")
        disk::usage data $MOUNT_ROOT
        disk::umount
        log_info "正在尝试修复硬盘: $dev ..."
        sudo e2fsck -yf "$dev"
        local res=$?
        if [[ $res -ne 0 && $res -ne 1 && $res -ne 2 ]]; then
            log_err "[$dev] 修复失败，请直接下电重新插拔硬盘，上电重试！"
            return 1
        fi
        ;;
        "6")
        ln -snf $MOUNT_ROOT/data $MDRIVE_DATA_ROOT
        log_ok "修改成功：$MDRIVE_DATA_ROOT -> $MOUNT_ROOT/data"
        ;;
        "7")
        sudo rm -rf "$MDRIVE_CACHE"/*
        log_ok "缓存清理成功：$MDRIVE_CACHE "
        ;;
    esac
    log_ok "修复完成，请手动重启服务！"
    return 0
}

#endregion

#region -------------------  vmc 包管理 ------------------

vmc::remote() {
    local action=$1
    case "$action" in
        "add")
            # sed -i -E "/^$2[[:space:]]+/d" "$REMOTE_CONFIG" 2>/dev/null
            local new_entry="$2 $3 $4"
            if [[ -f "$REMOTE_CONFIG" ]] && grep -Fxq "$new_entry" "$REMOTE_CONFIG"; then
                log_warn "配置 [$new_entry] 已存在"
            else
                echo "$new_entry" >> "$REMOTE_CONFIG"
                log_ok "分支 [$2] 已添加。"
            fi
            ;;
        "del")
            if [[ -z "$2" ]]; then
                log_err "请指定要删除的包名"
                return 1
            fi
            sed -i -E "/^$2[[:space:]]+/d" "$REMOTE_CONFIG"
            log_ok "分支 [$2] 远程配置已删除"
            ;;
        "list")
            log_info "当前远程分支列表:"
            [[ -f "$REMOTE_CONFIG" ]] && cat "$REMOTE_CONFIG" || echo "暂无分支"
            ;;
        *)
            echo "Usage: md remote list"
            echo "       md remote add <name> <branch> [platform]"
            echo "       md remote del <name>"
            ;;
    esac
}


vmc::_get_latest_ver() {
    local pkg_name=$1
    local branch=$2
    local platform=$3
    [[ "$branch" == "-" ]] && branch=""
    local search_filter="${platform:-orin}|any"
    local version
    version=$(vmc fsearch -n "$pkg_name" ${branch:+-v "$branch"} 2>/dev/null | \
        grep -iE "$search_filter" | \
        tail -n 1 | \
        sed -n 's/.*version: \([^,]*\).*/\1/p' | \
        tr -d '[:space:]')
    echo "$version"
}


# 获取当前已安装的版本
vmc::_get_current_ver() {
    local pkg_name=$1
    vmc list 2>/dev/null | grep "^$pkg_name " | awk '{print $2}' | tr -d '[:space:]()'
}


vmc::check_updates() {
    log_info "正在扫描配置并获取版本状态..."
    upgradable=()

    if [[ ! -f "$REMOTE_CONFIG" ]]; then
        log_err "配置文件不存在，请先添加分支"
        return 1
    fi
    echo "------------------------------------------------------------"
    while read -r pkg br plat; do
        [[ -z "$pkg" || "$pkg" =~ ^# ]] && continue
        local cur_ver lat_ver
        cur_ver=$(vmc::_get_current_ver "$pkg")
        lat_ver=$(vmc::_get_latest_ver "$pkg" "$br" "$plat")

        if [[ -n "$lat_ver" ]]; then
            upgradable+=("$pkg:$lat_ver:$br:$plat:$cur_ver")
            if [[ "$cur_ver" != "$lat_ver" ]]; then
                printf "%-15s ${YELLOW}%s (可更新)${NC}\n" "$pkg" "$lat_ver"
            else
                printf "%-15s ${GREEN}%s (已最新)${NC}\n" "$pkg" "$lat_ver"
            fi
        else
            printf "%-15s ${RED}%s${NC}\n" "$pkg" "未找到远程版本"
        fi
    done < "$REMOTE_CONFIG"
    echo "------------------------------------------------------------"
}


vmc::upgrade() {
    if flow::pre; then
        log_info "是否继续升级版本？('y'或回车继续，其他键退出)"
        read -r ans
        [[ "$ans" == "y" || "$ans" == "" ]] || return 0
    else
        log_info "是否继续升级版本？('f'强制继续，其他键退出)"
        read -r ans
        [[ "$ans" == "f" ]] || return 1
    fi

    vmc::check_updates
    if [[ ${#upgradable[@]} -eq 0 ]]; then
        log_ok "所有组件均已是最新，无需升级。"
        return 0
    fi
    # 多版本选择
    local final_queue=()
    local unique_pkgs
    unique_pkgs=$(for item in "${upgradable[@]}"; do echo "${item%%:*}"; done | sort -u)
    for pkg in $unique_pkgs; do
        local options=()
        for item in "${upgradable[@]}"; do
            [[ "$item" == "$pkg":* ]] && options+=("$item")
        done

        if [[ ${#options[@]} -eq 1 ]]; then
            local v c
            v=$(echo "${options[0]}" | cut -d':' -f2)
            c=$(echo "${options[0]}" | cut -d':' -f5)
            if [[ "$v" != "$c" ]]; then
                final_queue+=("${options[0]}")
            fi
        else
            log_info "发现 [$pkg] 存在多个分支配置，请选择目标版本:"
            for i in "${!options[@]}"; do
                local v b c
                v=$(echo "${options[$i]}" | cut -d':' -f2)
                b=$(echo "${options[$i]}" | cut -d':' -f3)
                c=$(echo "${options[$i]}" | cut -d':' -f5)
                local status=""
                [[ "$v" == "$c" ]] && status="${GREEN}(当前已安装)${NC}"
                echo -e "  [$i] 分支: $b | 版本: $v $status"
            done
            read -r -p "请选择序号 (跳过请输入 s, 默认 0): " choice
            choice=${choice:-0}
            [[ "$choice" == "s" ]] && continue
            final_queue+=("${options[$choice]}")
        fi
    done

    # 安装
    [[ ${#final_queue[@]} -eq 0 ]] && { log_warn "未选择任何安装项"; return 0; }
    read -r -p "确定执行升级? [Y/n]: " confirm
    [[ "$confirm" == "n" || "$confirm" == "N" ]] && return 0
    svc::manage stop soc1
    svc::manage stop soc2
    for q in "${final_queue[@]}"; do
        local n v
        n=$(echo "$q" | cut -d':' -f1)
        v=$(echo "$q" | cut -d':' -f2)
        log_info "正在安装 [$n] $v ..."
        if [[ $n == "mdrive_map" ]]; then
            vmc install -n "$n" -v "$v" --deps && log_ok "[$n] 安装成功"
        else
            vmc install -n "$n" -v "$v" && log_ok "[$n] 安装成功"
        fi
    done
    vmc list
    svc::manage start soc1
    svc::manage start soc2
}


# 获取版本信息
vmc::install(){
    if flow::pre; then
        log_info "是否继续升级版本？('y'或回车继续，其他键退出)"
        read -r ans
        [[ "$ans" == "y" || "$ans" == "" ]] || return 0
    else
        log_info "是否继续升级版本？('f'强制继续，其他键退出)"
        read -r ans
        [[ "$ans" == "f" ]] || return 1
    fi
    local tmp_file
    tmp_file=$(mktemp)
    log_info "即将打开 vi 编辑器，请粘贴版本信息，保存并退出后生效..."
    sleep 1
    vi "$tmp_file"
    input_text=$(< "$tmp_file")
    log_info "更新以下包版本："
    echo "$input_text"
    rm -f "$tmp_file"
    # 正则提取清洗
    _extract() {
    local pattern=$1
    echo "$input_text" | grep -iE "^[[:space:]]*(${pattern})" | head -n 1 | sed -r "
        s/^[[:space:]]*(${pattern})//i; # 删掉 key 本身（忽略大小写）
        s/^[[:space:]:：]*//;     # 删掉可能存在的冒号或空格
        s/^[[:space:]\"（(]*//;   # 删掉开头可能残留的空格、引号、左括号
        s/[[:space:]\"）)]*$//;   # 删掉结尾可能残留的空格、引号、右括号
        s/\r//g                   # 删掉 Windows 换行符
    "
    }
    wait
    for item in "${packages[@]}"; do
        local name="${item%%:*}"
        local pattern="${item##*:}"
        local version
        version=$(_extract "$pattern")
        if [[ -z "$version" ]]; then
            log_warn "\n跳过包 [$name]: 未在输入中提取到版本号"
            continue
        fi
        echo ""
        log_info "正在安装 [$name] 版本: $version ..."
        if [[ $name == "mdrive_map" ]]; then
            vmc install -n "$name" -v "$version" --deps && log_ok "[$name] 安装成功"
        else
            vmc install -n "$name" -v "$version" && log_ok "[$name] 安装成功"
        fi
    done
    svc::manage start soc1
    svc::manage start soc2
    vmc list
    # log_info "是否查看模块状态？('y'或回车继续，其他键退出)"
    # read -r ans
    # [[ "$ans" == "y" || "$ans" == "" ]] && svc::module || return 0
}


# 模糊更新单个包版本
vmc::finstall() {
    local version=$1
    local pkg_name
    pkg_name=$(vmc fsearch -v "$version" | tail -n 1 | awk -F'name: |, version:' '{print $2}')
    if [[ -n "$pkg_name" ]]; then
        log_info "下载安装 [${pkg_name}] ${version}..."
        if [[ $pkg_name == "mdrive_map" ]]; then
            vmc install -n "$pkg_name" -v "$version" --deps
        else
            vmc install -n "$pkg_name" -v "$version"
        fi
        vmc list
        log_ok "安装成功，手动重启服务或继续升级..."
    else
        log_err "未找到适用于 Orin 平台的包，请检查版本号是否正确！"
        return 1
    fi
}


# 回滚版本
vmc::rollback() {
    local pkg_name=""
    local search_v=""
    if [[ -z $1 ]]; then
        if [[ ! -f "$REMOTE_CONFIG" ]]; then
            log_err "未找到远程配置文件 $REMOTE_CONFIG，请先使用 md remote add 添加配置"
            return 1
        fi
        local choice
        choice=$(cat "$REMOTE_CONFIG" | fzf --header "选择要回滚的分支源:" --height=20% --layout=reverse)
        [[ -z "$choice" ]] && return
        read -r pkg_name branch_name _ <<< "$choice"
        # 处理分支名为 "-" 的情况
        search_v="$branch_name"
        [[ "$branch_name" == "-" ]] && search_v=""
    else
        search_v=$1
    fi

    log_info "正在搜索历史版本..."
    local versions_list
    versions_list=$(vmc fsearch ${pkg_name:+-n "$pkg_name"} ${search_v:+-v "$search_v"} -i 100 --verbose | awk '
        /^\[Index:/ {
            if (version) print time " | " version " | " platform;
            version=""; time=""; platform="";
        }
        /Platform:/ {
            $1=""; sub(/^[ \t]+/, "", $0); platform=$0
        }
        /Version:/ {
            $1=""; sub(/^[ \t]+/, "", $0); version=$0
        }
        /ReleaseTime:/ {
            $1=""; sub(/^[ \t]+/, "", $0);
            t=$0; sub(/T/, " ", t); time=substr(t, 1, 19);
        }
        END { if (version) print time " | " version " | " platform; }
    ' | sort -r)

    if [[ -z "$versions_list" ]]; then
        log_err "[$search_v] 未搜索到任何远程版本"
        return 1
    fi
    local selected_line
    selected_line=$(echo "$versions_list" | grep -E "$VMC_PLATFORM|any" | fzf \
        --ansi \
        --header "发布时间            |  远程版本号 (搜索关键字: $search_v)" \
        --layout=reverse \
        --height=100%)

    [[ -z "$selected_line" ]] && { log_warn "取消回滚"; return; }
    local selected_ver
    selected_ver=$(echo "$selected_line" | awk -F ' \| ' '{print $2}' | tr -d '[:space:]')

    log_warn "确定回滚 [$pkg_name] 到版本: $selected_ver ?"
    read -r -p "确认执行? [Y/n]: " confirm
    [[ "$confirm" == "n" || "$confirm" == "N" ]] && return

    # 停止服务
    svc::manage stop soc1
    svc::manage stop soc2
    sys::clean
    vmc::finstall "$selected_ver"
}

#endregion

#region ==================== WORKFLOW ====================

flow::pre() {
    local check_pass=true
    log_info "----------- Network Check -----------"

    printf "%-41s" "[网络] SOC2 :"
    if ssh $SSH_OPTS -q "$SOC2_IP" exit; then
        echo -e "${GREEN}正常${NC}"
    else
        echo -e "${RED}断开${NC}"
        return 1
    fi

    printf "%-41s" "[网络] $SERVER_IP :"
    if ping -c 1 -W 1 $SERVER_IP &> /dev/null; then
        echo -e "${GREEN}正常${NC}"
    else
        echo -e "${RED}断开${NC}"
        check_pass=false
    fi

    log_info "----------- Device Check ------------"
    local temp_dir
    temp_dir=$(mktemp -d)
    for device in "${INTERNAL_DEVICES[@]}"; do
        # 异步启动任务
        {
            local ip="${device%%:*}"
            local name="${device##*:}"
            name=$(echo "$name" | tr '/ ' '_')
            local result_file="$temp_dir/$name"
            local ping_res
            ping_res=$(ping -c 3 -W 2 -i 0.2 "$ip" 2>&1)
            local exit_code=$?
            if [[ $exit_code -eq 0 ]]; then
                local loss loss_display avg_ms
                loss=$(echo "$ping_res" | grep -oP '\d+(\.\d+)?(?=% packet loss)')
                avg_ms=$(echo "$ping_res" | grep 'rtt' | cut -d'/' -f5)
                loss_display=$(printf "%.1f" "$loss")
                printf "%-40s %-18b %s\n" "[设备] $name ($ip):" "${GREEN}在线${NC}" "[延迟: ${avg_ms}ms | 丢包: ${loss_display}%]" > "$result_file"
            else
                local reason="未知错误"
                [[ "$ping_res" =~ "Unreachable" ]] && reason="网络不可达"
                [[ "$ping_res" =~ "100% packet loss" ]] && reason="请求超时"
                printf "%-40s %-18b %s\n" "[设备] $name ($ip):" "${RED}离线${NC}" "($reason)" > "$result_file"
                echo "FAIL" > "$result_file.status"
            fi
        } &
    done
    wait
    for device in "${INTERNAL_DEVICES[@]}"; do
        local name="${device##*:}"
        name=$(echo "$name" | tr '/ ' '_')
        cat "$temp_dir/$name"
        [[ -f "$temp_dir/$name.status" ]] && check_pass=false
    done
    rm -rf "$temp_dir"

    log_info "------------ Time Check -------------"

    # 获取本地和远程时间戳
    local ts1 t1_str ts2 t2_str
    ts1=$(date +%s)
    t1_str=$(date +"%Y-%m-%d %H:%M:%S")
    ts2=$(ssh $SSH_OPTS "$SOC2_IP" date +%s)
    t2_str=$(ssh $SSH_OPTS "$SOC2_IP" "date +'%Y-%m-%d %H:%M:%S'")

    # 获取服务器时间 (尝试 curl，如果服务器不通则跳过)
    local ts_server=0
    local server_time_str="获取失败"

    # 获取 HTTP 头中的 Date 字段
    local http_date
    http_date=$(curl -Is --connect-timeout 2 $SERVER_IP | grep -i '^Date:' | cut -d' ' -f2-7 | tr -d '\r')

    if [[ -n "$http_date" ]]; then
        ts_server=$(date -d "$http_date" +%s 2>/dev/null)
        server_time_str=$(date -d "$http_date" +"%Y-%m-%d %H:%M:%S")
    fi

    printf "%-15s %s\n" "Server Time:" "$server_time_str"
    printf "%-15s %s\n" "SOC1 Time:"   "$t1_str"
    printf "%-15s %s\n" "SOC2 Time:"   "$t2_str"

    if [[ "$ts_server" -gt 0 ]]; then
        local diff1=$(( ts1 - ts_server )); diff1=${diff1#-}
        local diff2=$(( ts2 - ts_server )); diff2=${diff2#-}
        if [[ "$diff1" -le 20 && "$diff2" -le 20 ]]; then
            echo -e "时间同步状态: ${GREEN}正常 (误差 <= 20s)${NC}"
        else
            echo -e "时间同步状态: ${RED}异常! (SOC1误差:${diff1}s, SOC2误差:${diff2}s)${NC}"
            check_pass=false
        fi
    fi

    log_info "------- Disk Check (<85% Use) -------"

    disk::usage "Root (/)" "/"
    disk::usage "Cache (.cache)" $MDRIVE_CACHE
    disk::diagnose
    local res=$?
    if [[ $res -eq 0 ]]; then
        disk::usage "External ($DISK_LABEL)" $MOUNT_ROOT
    else
        log_warn "是否进行修复？('y'或回车继续，其他键退出)"
        read -r ans
        [[ "$ans" == "y" || "$ans" == "" ]] && disk::fix $res || check_pass=false
    fi
    echo "--------------------------------------------"
    svc::check soc1
    svc::check soc2
    if $check_pass; then
        log_ok "环境自检通过..."
        return 0
    else
        log_err "检测到环境异常 (网络/时间/硬盘/设备)"
        return 1
    fi

}

#endregion

#region ==================== COMPLETION ====================

_md_completions() {
    local cur prev opts
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    # 一级命令
    opts="init check umount upgrade install rollback rb stop start restart status log c channel m module record remote export e push pull"

    case "$prev" in
        stop|start|restart|status|log|c|channel)
            COMPREPLY=( $(compgen -W "soc1 soc2 1 2" -- "$cur") )
            return 0
            ;;
        remote)
            COMPREPLY=( $(compgen -W "add del list" -- "$cur") )
            return 0
            ;;
        record)
            COMPREPLY=( $(compgen -W "on off" -- "$cur") )
            return 0
            ;;
        remote)
            COMPREPLY=( $(compgen -W "add del list" -- "$cur") )
            return 0
            ;;
        rollback|rb)
            # 如果配置了远程分支，自动补全包名
            if [[ -f "$REMOTE_CONFIG" ]]; then
                local pkgs=$(awk '{print $1}' "$REMOTE_CONFIG")
                COMPREPLY=( $(compgen -W "$pkgs" -- "$cur") )
            fi
            return 0
            ;;
    esac

    if [[ $COMP_CWORD -eq 1 ]]; then
        COMPREPLY=( $(compgen -W "$opts" -- "$cur") )
        return 0
    fi
}

#endregion

#region ====================== CORE ======================

dispatch() {
    local cmd=$1
    shift
    case "$cmd" in
        "init")
            sys::nopasswd
            sys::init
            ;;
        "check")
            flow::pre
            ;;
        "start"|"stop"|"restart")
            if [[ "$1" == "soc1" || "$1" == "1" ]]; then
                svc::manage "$cmd" soc1
            elif [[ "$1" == "soc2" || "$1" == "2" ]]; then
                svc::manage "$cmd" soc2
            else
                svc::manage "$cmd" soc1
                svc::manage "$cmd" soc2
            fi
            ;;
        "status")
            if [[ "$1" == "soc1" || "$1" == "1" ]]; then
                svc::check soc1
            elif [[ "$1" == "soc2" || "$1" == "2" ]]; then
                svc::check soc2
            else
                svc::check soc1
                svc::check soc2
            fi
            ;;
        "log")
            svc::log "$@"
            ;;
        "module"|"m")
            svc::module
            ;;
        "channel"|"c")
            svc::channel "$@"
            ;;
        "record")
            svc::recorder "$@"
            ;;
        "remote")
            vmc::remote "$@"
            ;;
        "upgrade")
            vmc::upgrade
            ;;
        "rb"|"rollback")
            vmc::rollback "$@"
            ;;
        "install")
            svc::manage stop soc1
            svc::manage stop soc2
            sys::clean
            if [[ -n "$1" ]]; then
                vmc::finstall "$1"
            else
                vmc::install
            fi
            vmc list
            ;;
        "umount")
            svc::manage stop soc1
            svc::manage stop soc2
            disk::umount
            ;;
        "export"|"e")
            sys::export
            ;;
        "push")
            sys::push "$@"
            ;;
        "pull")
            sys::pull "$@"
            ;;
        *)
            log_err "未知命令: $cmd"
            usage
            ;;
    esac
}


main(){
    INSIDE_MD="false"
    if [[ -z $1 ]]; then
        usage
    else
        dispatch "$@"
    fi
}

main "$@"
#endregion
#endregion
