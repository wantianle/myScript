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
DEST_ROOT="$HOME"
PROJECT="/data/project"
CACHE="$PROJECT/.cache/data"
# VMC_CACHE="$PROJECT/.vmc/cache"
VMC_SOFTWARE="/mdrive"
DATA_SL="$PROJECT/data"
CONF_DIR_SOC1="/mdrive/mdrive_conf/supervisor/soc1/conf"
CONF_DIR_SOC2="/mdrive/mdrive_conf/supervisor/soc2/conf"
LOG_ROOT="/mdrive_data/log"
# 网络配置
REMOTE_USER="nvidia"
LOCAL_USER="mini"
REMOTE_IP="192.168.10.3"
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
    "192.168.10.22:TailScreen"
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
# 历史记录
export HISTFILE="$HOME/.md_history"
touch "$HISTFILE"
export HISTSIZE=1000
export HISTFILESIZE=1000
shopt -s histappend
export PROMPT_COMMAND="history -a; history -n; history -c; history -r;${PROMPT_COMMAND:-}"
# rsync
if command -v rsync &> /dev/null; then
    SYNC_TOOL="rsync"
else
    SYNC_TOOL="scp"
fi

#endregion

#region ===================== UTILS ======================

# run_node() {
#     local node=$1; shift
#     local cmd="$*"
#     case "$node" in
#         "soc1") eval "$cmd" ;;
#         "soc2") ssh $SSH_OPTS "$REMOTE_USER@$REMOTE_IP" "$cmd" ;;
#         "all")
#             eval "$cmd"
#             ssh $SSH_OPTS "$REMOTE_USER@$REMOTE_IP" "$cmd"
#             ;;
#     esac
# }

usage() {
    if [[ "$INSIDE_MD" == "true" ]]; then
        local prefix=""
    else
        local prefix="md "
    fi
    echo -e "${BLUE}Usage:${NC}"
    echo -e "  $prefix<c(ommand)> [a(rguments)]"
    echo -e "${BLUE}Commands:${NC}"
    echo -e "  -----------------------------------------------------------------------"
    printf "  ${YELLOW}%-25s${NC}  ${YELLOW}%s${NC}\n" "init"  "第一次使用工具需要初始化免密并安装工具到系统"
    printf "  %-25s  %s\n" "check"                             "检查车辆状态"
    printf "  %-25s  %s\n" "stop/start/restart/status"         "同时管理 soc1&2 服务，stop disk 安全弹出硬盘"
    printf "  %-25s  %s\n" "remote <add|del|list>"             "管理本地包对应的远程分支"
    printf "  %-25s  %s\n" ""                                  "  remote add <name> <branch> [platform]"
    printf "  %-25s  %s\n" ""                                  "  remote del <name>"
    printf "  %-25s  %s\n" "upgrade"                           "自动升级最新包版本"
    printf "  %-25s  %s\n" "install [version]"                 "手动升级指定版本"
    printf "  %-25s  %s\n" "log <(soc)1|(soc)2>"               "查看5分钟内 soc1/soc2 服务日志"
    printf "  %-25s  %s\n" "c(hannel) [(soc)1|(soc)2]"         "查看 soc1/soc2 channel 消息"
    printf "  %-25s  %s\n" "m(odule)"                          "管理 soc1&2 模块，查看对应模块日志和开发日志"
    printf "  %-25s  %s\n" "record [on]|<off>"                 "开启关闭 soc1&2 的Recorder和TestTool"

    # printf "  %-25s | %s\n" "push <src> [dst]"          "推送文件到宿主机 (默认 $DEST_ROOT)"
    # printf "  %-25s | %s\n" "pull <src> [dst]"          "从宿主机拉取文件到指定路径 (默认 $DEST_ROOT)"
    # printf "  %-25s | %s\n" "cl / clear"                "清空终端屏幕"
    # printf "  %-25s | %s\n" "q / exit"                  "退出交互模式"
    echo -e "  -----------------------------------------------------------------------"
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
        echo "推送公钥到车端：$REMOTE_USER@$REMOTE_IP..."
        ssh-copy-id -i "${KEY_PATH}.pub" "$REMOTE_USER@$REMOTE_IP"
    fi
    if ! grep -q "Host soc2" "$CONFIG_PATH"; then
        echo "配置 soc2 快捷登录：ssh soc2"
        cat << EOF >> "$CONFIG_PATH"
# Orin SOC2 快捷登录
Host soc2
    HostName $REMOTE_IP
    User $REMOTE_USER
EOF
        chmod 600 "$CONFIG_PATH"
    fi
    # 免密sudo
    if [[ ! -f $SUDO_PATH ]]; then
        echo "配置 soc1 免密 sudo..."
        echo 'nvidia ALL=(ALL) NOPASSWD: ALL' | sudo tee "$SUDO_PATH"
        sudo chmod 0440 "$SUDO_PATH"
        echo "配置 soc2 免密 sudo..."
        ssh $SSH_OPTS -t "$REMOTE_IP" "echo 'nvidia ALL=(ALL) NOPASSWD: ALL' | sudo tee $SUDO_PATH"
        ssh $SSH_OPTS "$REMOTE_IP" "sudo chmod 0440 $SUDO_PATH"
    fi
}


# 初始化命令行工具
sys::init(){
    if sudo cp "$HOME"/md.sh /usr/local/bin/md &>/dev/null && sudo chmod +x /usr/local/bin/md; then
        log_ok "初始化完成！现在可以通过 md [command] [arguments] 对 mdrive 进行管理"
        echo -e "试试输入: ${GREEN}md check${NC}"
    else
        log_err "初始化失败，请检查 $HOME/md.sh 是否存在！"
    fi
}


sys::date(){
    echo -n "[soc1]date: "
    date
    echo -n "[soc2]date: "
    ssh $SSH_OPTS "$REMOTE_IP" "date"
}


# 清理内盘数据
sys::clean(){
    local avail
    avail=$(df -BG "$CACHE" | awk 'NR==2 {print $4}' | tr -d 'G')
    if [[ "$avail" -lt 5 ]]; then
        log_warn "系统剩余空间不足 5GB (当前: ${avail}GB)，过低会影响 OTA 版本升级，是否需要清理？(y/n)"
        read -r confirm
        [[ "$confirm" != "y" ]] && return
        log_info "正在清理缓存：$CACHE "
        sudo rm -rf "$CACHE"/*
    fi
}


# 推送数据到电脑
sys::push(){
    local src_path=$1
    local dest_path=$2
    local host_ip
    host_ip=$(echo "$SSH_CONNECTION" | awk '{print $1}')
    if [[ -z "$src_path" ]]; then
        echo "usage: push <src_path> [dest_path]"
        return
    fi
    log_info "正在推送 ${src_path} ==> $LOCAL_USER@$host_ip:${dest_path:-$DEST_ROOT}"
    if [[ "$SYNC_TOOL" == "rsync" ]]; then
    echo "rsync"
        rsync -rlptvzP "$src_path" "$LOCAL_USER@$host_ip:${dest_path:-$DEST_ROOT}"
    else
        scp -r "$src_path" "$LOCAL_USER@$host_ip:${dest_path:-$DEST_ROOT}"
    fi
}


# 拉取数据到车机端
sys::pull(){
    local src_path=$1
    local dest_path=$2
    local host_ip
    host_ip=$(echo "$SSH_CONNECTION" | awk '{print $1}')
    if [[ -z "$dest_path" ]]; then
        echo "usage: pull [src_path] [dest_path]"
        return
    fi
    log_info "正在拉取 $LOCAL_USER@$host_ip:${src_path} ==> ${dest_path:-$DEST_ROOT}"
    if [[ "$SYNC_TOOL" == "rsync" ]]; then
        rsync -rlptvzP --protect-args "$LOCAL_USER@$host_ip:$src_path" "${dest_path:-$DEST_ROOT}"
    else
        scp -r "$LOCAL_USER@$host_ip:$src_path" "${dest_path:-$DEST_ROOT}"
    fi
}

#endregion

#region -------------------  svc 服务层 ------------------

# 查看服务运行标识
svc::check() {
    if systemctl is-active --quiet mdrive.service; then
        echo -e "[soc1]服务状态: ${GREEN}Running${NC}"
    else
        echo -e "[soc1]服务状态: ${RED}Stopped or Failed${NC}"
    fi
    ssh $SSH_OPTS "$REMOTE_IP" "systemctl is-active --quiet mdrive.service"
    local status=$?
    if [[ $status -eq 0 ]]; then
        echo -e "[soc2]服务状态: ${GREEN}Running${NC}"
    elif [[ $status -ne 255 ]]; then
        echo -e "[soc2]服务状态: ${RED}Stopped or Failed${NC}"
    fi
}


# 详细查看服务状态
svc::status(){
    if [[ $1 == "soc1" || $1 == "" ]]; then
        systemctl status mdrive.service
    elif [[ $1 == "soc2" ]]; then
        ssh $SSH_OPTS -t "$REMOTE_IP" "systemctl status mdrive.service"
    fi
}


# 管理服务
svc::manage(){
    local action=$1
    log_info "$action mdrive service..."
    sudo systemctl $action mdrive.service
    ssh $SSH_OPTS "$REMOTE_IP" "timeout 15 sudo systemctl $action mdrive.service"
    svc::check
}


# 查看日志
svc::log(){
    case "$1" in
        "soc1"|"1"|"")
            sudo journalctl -eu mdrive.service --since "5 min ago" -f --no-pager | grep --line-buffered -v -E "ptp4l|phc2sys"
            ;;
        "soc2"|"2")
            ssh $SSH_OPTS -t "$REMOTE_IP" 'sudo journalctl -eu mdrive.service --since "5 min ago" -f --no-pager | grep --line-buffered -v -E "ptp4l|phc2sys"'
            ;;
        *)
            echo "usage: log <soc1|soc2>"
            ;;
    esac
}


# recorder
svc::recorder(){
    if disk::check; then
        if [[ $1 == "on" || $1 == "" ]]; then
            local avail
            avail=$(df -BG "$MOUNT_ROOT" | awk 'NR==2 {print $4}' | tr -d 'G')
            if [[ "$avail" -lt 300 ]]; then
                log_warn "数据盘剩余空间不足 300GB (当前: ${avail}GB)！确定要录制吗？(y/n)"
                read -r confirm
                [[ "$confirm" != "y" ]] && return
            fi
            supervisorctl start Recorder
            supervisorctl start TestTool
            ssh $SSH_OPTS "$REMOTE_IP" "supervisorctl start Recorder"
        elif [[ $1 == "off" ]]; then
            supervisorctl stop Recorder
            supervisorctl stop TestTool
            ssh $SSH_OPTS "$REMOTE_IP" "supervisorctl stop Recorder"
        else
            usage
        fi
    fi
}


svc::channel(){
    case "$1" in
        "soc1"|"1"|"")
            cyber_monitor
            ;;
        "soc2"|"2")
            ssh $SSH_OPTS -t "$REMOTE_IP" "export MDRIVE_ROOT_DIR='/mdrive' && export MDRIVE_DEP_DIR='/mdrive/mdrive_dep' && source $VMC_SOFTWARE/mdrive/setup.sh && cyber_monitor"
            ;;
        *)
            echo "usage: md c(hannel) (soc)1|(soc)2"
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
            if [[ -f "$path" ]]; then
                sudo less -R -S --follow-name +F "$path"
            else
                echo -e "找不到日志文件 $path"
                read -r -n 1 -p "按任意键继续..."
            fi
            ;;
        "start"|"stop"|"restart")
            echo -e "正在对 [$soc] $mod 执行 $action..."
            if [[ "$soc" == "soc1" ]]; then
                sudo supervisorctl "$action" "$mod"
            else
                ssh $SSH_OPTS "$REMOTE_IP" "sudo supervisorctl $action $mod"
            fi
            sleep 1
            ;;
    esac
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
    local dev mnt
    dev=$(disk::_get_dev)
    mnt=$(disk::_get_mnt_dev)
    if [[ -n "$dev" && "$mnt" == "$dev" ]]; then
        echo -e "[soc1]硬盘: ${GREEN}Mounted${NC}"
    else
        echo -e "[soc1]硬盘: ${RED}Umounted${NC}"
    fi
    if ssh $SSH_OPTS "$REMOTE_IP" "timeout 2 mountpoint -q $MOUNT_ROOT"; then
        echo -e "[soc2]硬盘: ${GREEN}Mounted${NC}"
    else
        echo -e "[soc2]硬盘: ${RED}Umounted/Error${NC}"
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
disk::eject(){
    sync && sync
    while mountpoint -q /media/data; do
        sudo umount -l /media/data 2>/dev/null
    done
    ssh $SSH_OPTS $REMOTE_IP "sudo umount -l /media/data 2>/dev/null"
    log_ok "硬盘卸载成功..."
}


disk::diagnose(){
    # return 1 无硬盘 2 未挂载 3 挂载残留 4 挂载点访问超时 5 I/O错误（盘满或损坏）6 软链接路径指向错误
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

    ssh $SSH_OPTS "$REMOTE_IP" "mountpoint -q $MOUNT_ROOT"
    local res=$?
    if [[ ! $res =~ ^(0|130|255)$ ]]; then
        log_err "硬盘未挂载 soc2:$MOUNT_ROOT"
        return 2
    fi

    if [[ $mnt != "$dev" ]]; then
        log_err "挂载目录被占用 $mnt"
        return 3
    fi

    if ! timeout 2 stat -t "$MOUNT_ROOT" >/dev/null 2>&1; then
        log_err "挂载目录无法访问 $MOUNT_ROOT"
        return 4
    fi

    if ! ssh $SSH_OPTS "$REMOTE_IP" "timeout 2 stat -t $MOUNT_ROOT >/dev/null 2>&1"; then
        log_err "挂载目录无法访问 $MOUNT_ROOT"
        return 4
    fi

    if grep "$MOUNT_ROOT" /proc/mounts | grep -q " ro,"; then
        log_err "文件系统已降级为 [只读] soc1:${MOUNT_ROOT}"
        return 5
    fi

    if ssh $SSH_OPTS "$REMOTE_IP" "grep $MOUNT_ROOT /proc/mounts | grep -q ' ro,'"; then
        log_err "文件系统已降级为 [只读] soc2:${MOUNT_ROOT}"
        return 5
    fi

    local path
    path=$(readlink -f $DATA_SL)
    if [[ $path != "$MOUNT_ROOT/data" ]]; then
        log_warn "路径链接指向错误 $DATA_SL -> $path"
        return 6
    fi

    local avail
    avail=$(df -BG "$CACHE" | awk 'NR==2 {print $4}' | tr -d 'G')
    if [[ "$avail" -lt 5 ]]; then
        log_warn "$CACHE 剩余空间不足 5GB (当前: ${avail}GB)，过低会影响 OTA 版本升级"
        return 7
    fi

    return 0
}


# 修复硬盘损坏
disk::fix(){
    # return 1 无硬盘 2 未挂载 3 挂载残留 4 挂载点访问超时 5 I/O错误（盘满或损坏）
    local dev
    dev=$(disk::_get_dev)
    local err_code=$1
    svc::manage stop
    log_info "开始执行修复程序 (Error Code: $err_code)..."
    case "$err_code" in
        "1")
        log_warn "检查并重启电源：1.硬盘是否插好 2.盘符是否为 data 3.硬盘/硬盘线可能损坏 "
        return 1
        ;;
        "2"|"3")
        disk::eject
        log_ok "挂载清理完成！"
        ;;
        "4"|"5")
        disk::usage "data" $MOUNT_ROOT
        disk::eject
        log_info "正在尝试修复硬盘: $dev ..."
        sudo e2fsck -yf "$dev"
        local res=$?
        if [[ $res -ne 0 && $res -ne 1 && $res -ne 2 ]]; then
            log_err "[$dev] 修复失败，请直接下电重新插拔硬盘，上电重试！"
            return 1
        fi
        ;;
        "6")
        ln -snf $MOUNT_ROOT/data $DATA_SL
        log_ok "修改成功：$DATA_SL -> $MOUNT_ROOT/data"
        ;;
        "7")
        sudo rm -rf "$CACHE"/*
        log_ok "缓存清理成功：$CACHE "
        ;;
    esac
    log_ok "修复完成，请手动重启服务！"
    return 0
}


# 注释掉 /etc/udev/rules.d/99-nv_usb-automount_default.rules
disk::fix_nvmount(){
    local target_file
    target_file="/etc/udev/rules.d/99-nv_usb-automount_default.rules"
    if [[ ! -f "$target_file" ]]; then
        log_err "找不到文件 $target_file"
        return 1
    fi
    log_info "创建备份文件 ${target_file}.bak..."
    cp "$target_file" "${target_file}.bak"
    # ^[^#] 匹配所有开头不是 # 的行
    # s/^/#/ 在行首插入 #
    # -i 直接修改文件
    if sudo sed -i 's/^[^#]/#/g' "$target_file"; then
        sudo udevadm control --reload-rules
        sudo udevadm trigger
        log_ok "nvidia 自动挂载服务已禁用。"
    fi
}
#endregion

#region -------------------  vmc 包管理 ------------------

vmc::remote() {
    local action=$1
    case "$action" in
        "add")
            # 用法: md remote add [name] [branch] [platform]
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
            # 用法: md remote del [name]
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
    upgradable=() # 候选列表

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
    log_info "可升级列表:"
    for q in "${final_queue[@]}"; do echo "$q" | tr ':' ' => '; done
    read -r -p "确定执行升级? [Y/n]: " confirm
    [[ "$confirm" == "n" || "$confirm" == "N" ]] && return 0
    svc::manage stop
    for q in "${final_queue[@]}"; do
        local n v
        n=$(echo "$q" | cut -d':' -f1)
        v=$(echo "$q" | cut -d':' -f2)
        log_info "正在安装 [$n] $v ..."
        vmc install -n "$n" -v "$v" && log_ok "[$n] 成功"
    done
    vmc list
    svc::manage start
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
        if ! vmc install -n "$name" -v "$version"; then
            log_err "[$name] 安装过程中出现错误！"
            return 1
        fi
    done
    svc::manage start
    vmc list
    log_info "是否查看模块状态？('y'或回车继续，其他键退出)"
    read -r ans
    [[ "$ans" == "y" || "$ans" == "" ]] && fzf_module || return 0
}


# 模糊更新单个包版本
vmc::finstall() {
    local version=$1
    local pkg_name
    pkg_name=$(vmc fsearch -v "$version" | tail -n 1 | awk -F'name: |, version:' '{print $2}')
    if [[ -n "$pkg_name" ]]; then
        log_info "下载安装 [${pkg_name}] ${version}..."
        if vmc install -n "$pkg_name" -v "$version"; then
            log_ok "升级成功，手动重启服务或继续升级..."
        fi
    else
        log_err "未找到适用于 Orin 平台的包，请检查版本号是否正确！"
        return 1
    fi
}


#endregion

#region -------------------- log 日志层 ------------------

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok()  { echo -e "${GREEN}[ok]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_err() { echo -e "${RED}[ERROR]${NC} $1"; }

# 智能搜索日志文件路径 (零子进程, 极速响应)
log_get_path() {
    local soc=$1
    local mod=$2
    local type=$3
    local target_file=""
    local conf_dir="$CONF_DIR_SOC1"
    [[ "$soc" == "soc2" ]] && conf_dir="$CONF_DIR_SOC2"

    local conf_file=""
    set -- "$conf_dir"/"$mod".conf
    [[ -f "$1" ]] && conf_file="$1"
    [[ -z "$conf_file" ]] && return
    local raw_cmd=""
    local sv_log=""
    while read -r line || [[ -n "$line" ]]; do
        if [[ "$line" =~ ^stdout_logfile= ]]; then
            sv_log="${line#*=}"
            sv_log="${sv_log%%;*}"
            sv_log="${sv_log//[[:space:]]/}"
        elif [[ "$line" =~ /mdrive/bin ]]; then
            raw_cmd="$line"
        fi
    done < "$conf_file"
    # --- 情况 A: SV 日志直接返回 ---
    if [[ "$type" == "sv" ]]; then
        echo "$sv_log"; return
    fi

    # --- 情况 B: Glog 智能探测 ---
    local bin_name=""
    local bin_path
    bin_path=$(echo "$raw_cmd" | grep -oP '/mdrive/(bin|scripts)/[^ ]+')
    bin_name="${bin_path##*/}"
    bin_name="${mod#mdrive_}"
    bin_name="${mod,,}"
    # 构造搜索优先级数组
    local base_name="${bin_name#mdrive_}" # 去掉 mdrive_ 前缀
    local mod_lower="${mod,,}"
    local mod_clean="${mod_lower#mdrive_}"

    # 按优先级探测软链接 (.INFO)
    # 优先级顺序：二进制名 > 去掉前缀名 > 模块名 > 模块去掉前缀名
    local candidates=(
        "${bin_name}.INFO"
        "${base_name}.INFO"
        "${mod_lower}.INFO"
        "${mod_clean}.INFO"
    )
    for c in "${candidates[@]}"; do
        if [[ -L "$LOG_ROOT/$c" || -f "$LOG_ROOT/$c" ]]; then
            echo "$LOG_ROOT/$c"
            return
        fi
    done
    # 模糊搜索 (针对 TestTool 这种前面加了 tools_ 的情况)
    # 在日志目录寻找包含 mod_clean 且以 .INFO 结尾的最新的文件
    local fuzzy
    fuzzy=$(find "$LOG_ROOT" -maxdepth 1 -name "*${mod_clean}*.INFO" -print0 2>/dev/null | xargs -0 ls -t 2>/dev/null | head -n 1)
    if [[ -n "$fuzzy" ]]; then
        echo "$fuzzy"
        return
    fi

}

#endregion

#region -------------------   ui 交互层 ------------------

# 获取并格式化双端状态
# 输出格式：[颜色代码] [soc1] 模块名   RUNNING   pid 123, uptime 1:23 [重置代码]
# - RUNNING 且 uptime > 10s (0:00:1x) -> 绿色
# - RUNNING 且 uptime < 10s (0:00:0x) -> 黄色 (疑似重启中)
# - 其他 (STOPPED, FATAL, BACKOFF, EXITED) -> 红色
fetch_combined() {
    local s1 s2
    s1=$(sudo supervisorctl status | awk '{print "soc1 " $0}')
    s2=$(ssh $SSH_OPTS "$REMOTE_IP" "sudo supervisorctl status" 2>/dev/null | awk '{print "soc2 " $0}')
    printf "%s\n" "$s1" "$s2" | while read -r line; do
        local clean_line soc mod state tail
        clean_line=$(echo "$line" | tr -s ' ')
        read -r soc mod state tail <<< "$clean_line"
        if [[ "$state" == "RUNNING" ]]; then
            if echo "$tail" | grep -q "uptime 0:00:0"; then
                printf "${YELLOW}[%-4s] %-25s %-8s %s${NC}\n" "$soc" "$mod" "$state" "$tail"
            else
                printf "${GREEN}[%-4s] %-25s %-8s %s${NC}\n" "$soc" "$mod" "$state" "$tail"
            fi
        else
            printf "${RED}[%-4s] %-25s %-8s %s${NC}\n" "$soc" "$mod" "$state" "$tail"
        fi
    done
}
export -f fetch_combined svc::mod_handler log_get_path
export CONF_DIR_SOC1 CONF_DIR_SOC2 LOG_ROOT SSH_OPTS REMOTE_IP RED GREEN YELLOW BLUE NC

fzf_module() {
    if ! command -v fzf &> /dev/null; then
        log_warn "请先安装 fzf..."
        return 1
    fi
    fetch_combined | fzf \
        --ansi \
        --height 95% \
        --reverse \
        --header "操作: Enter:模块日志 | Alt-Enter:研发日志 | Alt-S:启动 | Alt-X:停止 | Alt-R:重启 | Ctrl-R:刷新" \
        --bind "enter:execute(svc::mod_handler {} sv)" \
        --bind "alt-enter:execute(svc::mod_handler {} glog)" \
        --bind "alt-s:execute(svc::mod_handler {} start)+reload(fetch_combined)" \
        --bind "alt-x:execute(svc::mod_handler {} stop)+reload(fetch_combined)" \
        --bind "alt-r:execute(svc::mod_handler {} restart)+reload(fetch_combined)" \
        --bind "ctrl-r:reload(fetch_combined)" \
        --bind "esc:abort"
}

#endregion

#region ==================== WORKFLOW ====================

flow::pre() {
    local check_pass=true
    log_info "----------- Network Check -----------"

    printf "%-41s" "[网络] SOC2 :"
    if ssh $SSH_OPTS -q "$REMOTE_IP" exit; then
        echo -e "${GREEN}正常${NC}"
    else
        echo -e "${RED}断开${NC}"
        return 1
    fi

    printf "%-41s" "[网络] $SERVER_IP :"
    if ping -c 1 -W 2 $SERVER_IP &> /dev/null; then
        echo -e "${GREEN}正常${NC}"
    else
        echo -e "${RED}断开${NC}"
        check_pass=false
    fi

    log_info "----------- Device Check ------------"
    local temp_dir
    temp_dir=$(mktemp -d) # 创建临时目录存放结果
    for device in "${INTERNAL_DEVICES[@]}"; do
        # 异步启动任务
        {
            local ip="${device%%:*}"
            local name="${device##*:}"
            name=$(echo "$name" | tr '/ ' '_')
            local result_file="$temp_dir/$name"
            local ping_res
            ping_res=$(ping -c 5 -W 1 "$ip" 2>&1)
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
    ts2=$(ssh $SSH_OPTS "$REMOTE_IP" date +%s)
    t2_str=$(ssh $SSH_OPTS "$REMOTE_IP" "date +'%Y-%m-%d %H:%M:%S'")

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
    disk::usage "Cache (.cache)" "$CACHE"
    disk::diagnose
    local res=$?
    if [[ $res -eq 0 ]]; then
        disk::usage "External ($DISK_LABEL)" "$MOUNT_ROOT"
    else
        log_warn "是否进行修复？('y'或回车继续，其他键退出)"
        read -r ans
        [[ "$ans" == "y" || "$ans" == "" ]] && disk::fix $res || check_pass=false
    fi
    echo "--------------------------------------------"
    svc::check
    if $check_pass; then
        log_ok "环境自检通过..."
        return 0
    else
        log_err "检测到环境异常 (网络/时间/硬盘/设备)"
        return 1
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
        "status")
            svc::check
            ;;
        "details")
            svc::status "$@"
            ;;
        "start")
            svc::manage start
            ;;
        "stop")
            if [[ $1 == "disk" ]]; then
                svc::manage stop
                disk::eject
            else
                svc::manage stop
            fi
            ;;
        "restart")
            svc::manage restart
            ;;
        "log")
            svc::log "$@"
            ;;
        "module"|"m")
            fzf_module
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
        "install")
            svc::manage stop
            sys::clean
            if [[ -n "$1" ]]; then
                vmc::finstall "$1"
            else
                vmc::install
            fi
            vmc list
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
    fi
    dispatch "$@"
}

main "$@"
#endregion
#endregion
