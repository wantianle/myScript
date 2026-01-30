#!/usr/bin/env bash

RED='\033[1;31m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
NC='\033[0m'
# 定义原始颜色码 (使用 \001 \002 确保 Readline 兼容性)
C_BG_G=$'\001\e[1;32m\002' # 绿底白字
C_FG_B=$'\001\e[1;34m\002'    # 蓝色粗体
C_NC=$'\001\e[0m\002'         # 重置

# 效果: [ MDRIVE ] >
PROMPT="${C_BG_G}MDRIVE${C_NC}${C_FG_B} ❯${C_NC} "
HISTFILE="$HOME/.md_history"
touch "$HISTFILE"

KEY_PATH="$HOME/.ssh/id_ed25519"
CONFIG_PATH="$HOME/.ssh/config"
REMOTE_USER="nvidia"
LOCAL_USER="mini"
REMOTE_IP="192.168.10.3"
SSH_OPTS="-o ConnectTimeout=3 -o ConnectionAttempts=1"
DISK_LABEL="data"
MOUNT_ROOT="/media/data"
DEST_ROOT="$HOME"
CACHE="/data/project/.cache/data/*"
VMC_CACHE="/data/project/.vmc/cache"
VMC_SOFTWARE="/mdrive"
if command -v rsync &> /dev/null; then
    SYNC_TOOL="rsync"
else
    SYNC_TOOL="scp"
fi

usage() {
    if [[ "$INSIDE_MD" == "true" ]]; then
        local prefix=""
    else
        local prefix="md "
    fi
    echo -e "${BLUE}用法 (Usage):${NC}"
    echo -e "  $prefix<command> [arguments]"
    echo ""
    echo -e "${BLUE}核心命令 (Commands):${NC}"
    echo -e "  -----------------------------------------------------------------------"
    printf "  ${YELLOW}%-18s${NC} | ${YELLOW}%s${NC}\n" "init"  "第一次使用工具需要初始化免密并安装工具到系统"
    printf "  %-18s | %s\n" "check"            "快速检查双端 (soc1/soc2) 服务存活状态"
    printf "  %-18s | %s\n" "status [socn]"    "查看 systemctl 详情 (默认 soc1)"
    printf "  %-18s | %s\n" "start"            "开启双端 mdrive 服务"
    printf "  %-18s | %s\n" "stop [disk]"      "关闭双端服务 (参数 disk 可顺带卸载数据盘)"
    printf "  %-18s | %s\n" "restart"          "重启双端服务"
    printf "  %-18s | %s\n" "log <socn>"       "查看十分钟内日志。示例: md log soc1"
    printf "  %-18s | %s\n" "install [n] [v]"  "根据 name version 手动升级包，无参则多包升级模式"
    printf "  %-18s | %s\n" "remove [n|all]"   "根据 name 卸载包清除缓存文件，all 则全部卸载清除"
    printf "  %-18s | %s\n" "push <src> [dst]" "推送文件到宿主机 (默认 $DEST_ROOT)"
    printf "  %-18s | %s\n" "pull <src> [dst]" "从宿主机拉取文件到指定路径 (默认 $DEST_ROOT)"
    printf "  %-18s | %s\n" "fixdisk"          "修复数据盘文件系统错误 (fsck)"
    printf "  %-18s | %s\n" "clean"            "清理缓存，解决升级token错误"
    printf "  %-18s | %s\n" "cl / clear"       "清空终端屏幕"
    printf "  %-18s | %s\n" "q / exit"         "退出交互模式"
    echo -e "  -----------------------------------------------------------------------"
    echo ""
    echo -e "${BLUE}示例 (Examples):${NC}"
    echo -e "  ${prefix}log soc2 -f            # 实时监控 SOC2 日志"
    echo -e "  ${prefix}install mdrive test.xxxx  # 安装指定版本"
    echo -e "  ${prefix}stop disk              # 停止服务并卸载硬盘"
    echo ""
}


# 免密处理
nopasswd(){
    # 免密ssh
    if [ ! -f "$KEY_PATH" ]; then
        echo "未发现密钥，正在生成默认密钥..."
        ssh-keygen -t ed25519 -f "$KEY_PATH" -N ""
        echo "推送公钥到车端：$REMOTE_USER@$REMOTE_IP..."
        ssh-copy-id -i "${KEY_PATH}.pub" "$REMOTE_USER@$REMOTE_IP"
    fi
    if ! grep -q "Host soc2" $CONFIG_PATH; then
        echo "配置 soc2 快捷登录：ssh soc2"
        cat << EOF >> $CONFIG_PATH
# Orin SOC2 快捷登录
Host soc2
    HostName $REMOTE_IP
    User $REMOTE_USER
EOF
    fi
    chmod 600 $CONFIG_PATH
    # 免密sudo
    echo "配置 soc1 免密 sudo..."
    echo 'nvidia ALL=(ALL) NOPASSWD: ALL' | sudo tee /etc/sudoers.d/mdrive_perms
    sudo chmod 0440 /etc/sudoers.d/mdrive_perms
    echo "配置 soc2 免密 sudo..."
    ssh $SSH_OPTS -t $REMOTE_IP "echo 'nvidia ALL=(ALL) NOPASSWD: ALL' | sudo tee /etc/sudoers.d/mdrive_perms"
    ssh $SSH_OPTS $REMOTE_IP "sudo chmod 0440 /etc/sudoers.d/mdrive_perms"
}


# 初始化命令行工具
cli_init(){
    sudo cp $HOME/md.sh /usr/local/bin/md
    sudo chmod +x /usr/local/bin/md
    if [[ $? -eq 0 ]]; then
        echo -e "${GREEN}初始化完成！现在可以通过 "md [command] [arguments]" 对 mdrive 进行管理${NC}"
        echo -e "试试输入: ${GREEN}md check${NC}"
    else
        echo -e "${RED}初始化失败，请检查 $HOME/md.sh 是否存在！${NC}"
    fi
}


# 查看服务运行标识
check_status() {
    if [[ $1 == "soc1" || $1 == "" ]]; then
        if systemctl is-active --quiet mdrive.service; then
            echo -e "soc1 服务状态: ${GREEN}Running${NC}"
        else
            echo -e "soc1 服务状态: ${RED}Stopped or Failed${NC}"
        fi
    fi
    if [[ $1 == "soc2" || $1 == "" ]]; then
        ssh $SSH_OPTS $REMOTE_IP "systemctl is-active --quiet mdrive.service"
        local status=$?
        if [[ $status -eq 0 ]]; then
            echo -e "soc2 服务状态: ${GREEN}Running${NC}"
        elif [[ $status -ne 255 ]]; then
            echo -e "soc2 服务状态: ${RED}Stopped or Failed${NC}"
        fi
    fi
}


# 详细查看服务状态
status_service(){
    if [[ $1 == "soc1" || $1 == "" ]]; then
        systemctl status mdrive.service
    elif [[ $1 == "soc2" ]]; then
        ssh $SSH_OPTS -t "$REMOTE_IP" "systemctl status mdrive.service"
    fi
}


# 启动服务
start_service(){
    echo -e "${GREEN}正在启动服务...${NC}"
    sudo systemctl start mdrive.service
    local res1=$?
    check_status soc1
    ssh $SSH_OPTS $REMOTE_IP "sudo systemctl start mdrive.service"
    local res2=$?
    check_status soc2
    if [[ $res1 -ne 0 || $res2 -ne 0 ]]; then
        echo -e "${YELLOW}检测到启动异常，建议执行 'log' 命令查看对应 soc 日志。${NC}"
    fi
}


# 关闭服务
stop_service(){
    echo -e "${GREEN}正在关闭服务...${NC}"
    sudo systemctl stop mdrive.service
    if [[ $? -eq 0 ]]; then
        echo -e "${GREEN}soc1 服务已关闭！${NC}"
    fi
    ssh $SSH_OPTS "$REMOTE_IP" "sudo systemctl stop mdrive.service"
    local res=$?
    if [[ $res -eq 0 ]]; then
        echo -e "${GREEN}soc2 服务已关闭！${NC}"
    fi
    if [[ $1 == "disk" ]]; then
        sync && sync
        umount -l /media/data 2>/dev/null
        sleep 1
        echo "硬盘已安全卸载..."
    fi
}


# 查看日志
watch_log(){
    case "$1" in
        "soc1"|"")
            sudo journalctl -eu mdrive.service --since "10 min ago" -f --no-pager | grep --line-buffered -v -E "ptp4l|phc2sys"
            ;;
        "soc2")
            ssh $SSH_OPTS -t "$REMOTE_IP" "sudo journalctl -eu mdrive.service --since ‘10 min ago’ -f --no-pager | grep --line-buffered -v -E 'ptp4l|phc2sys'"
            ;;
        *)
            echo "usage: log <soc1|soc2>"
            ;;
    esac
}


# 正则提取清洗
extract_version() {
    local key_pattern=$1
    echo "$input_text" | grep -iE "^[[:space:]]*(${key_pattern})" | head -n 1 | sed -r "
        s/^[[:space:]]*(${key_pattern})//i; # 删掉 key 本身（忽略大小写）
        s/^[[:space:]:：]*//;     # 删掉可能存在的冒号或空格
        s/^[[:space:]\"（(]*//;   # 删掉开头可能残留的空格、引号、左括号
        s/[[:space:]\"）)]*$//;   # 删掉结尾可能残留的空格、引号、右括号
        s/\r//g                   # 删掉 Windows 换行符
    "
}


# 获取版本信息
get_version(){
    local tmp_file=$(mktemp)
    echo -e "${BLUE}即将打开 vi 编辑器，请粘贴版本信息，保存并退出后生效...${NC}"
    sleep 1
    vi "$tmp_file"
    input_text=$(cat "$tmp_file")
    rm -f "$tmp_file"
    mdrive=""; mdrive_conf=""; mdrive_map=""; mdrive_dep=""; mdrive_model=""
    mdrive=$(extract_version "mdrive")
    mdrive_conf=$(extract_version "mdrive_conf|conf")
    mdrive_map=$(extract_version "mdrive_map|map")
    mdrive_dep=$(extract_version "mdrive_dep|dep")
    mdrive_model=$(extract_version "mdrive_model|model")
}


# 更新单个包版本
vmc_install(){
    local pkg_name=$1
    local version=$2
    if [[ -n $version ]]; then
        echo -e "${GREEN}下载安装 [${pkg_name}] ${version}...${NC}"
        vmc install -n $pkg_name -v $version
    else
        echo -e "${YELLOW}${pkg_name} 未检测到新版本！${NC}"
    fi
}


# 更新所有版本
sync_version(){
    stop_service
    vmc_install mdrive $mdrive
    vmc_install mdrive_conf $mdrive_conf
    vmc_install mdrive_map $mdrive_map
    vmc_install mdrive_dep $mdrive_dep
    vmc_install mdrive_model $mdrive_model
    start_service
    vmc list
}


# 模糊下载
fuzzy_install() {
    stop_service
    local version=$1
    local pkg_name=$(vmc fsearch -v "$version" | grep -iE "orin|any" | head -n 1 | awk -F'name: |, version:' '{print $2}')
    if [[ -n "$pkg_name" ]]; then
        echo -e "${GREEN}下载安装 [${pkg_name}] ${version}...${NC}"
        vmc install -n "$pkg_name" -v "$version"
        if [[ $? -eq 0 ]]; then
            echo -e "${GREEN}升级成功，手动重启服务或继续升级其他包: ${NC}md start / md install <other package>"
        fi
    else
        echo -e "${RED}未找到适用于 Orin 平台的包，请检查版本号是否正确。${NC}"
        return 1
    fi
}


# 若硬盘固定，推送数据到电脑
push_data(){
    local src_path=$1
    local dest_path=$2
    local host_ip=$(echo $SSH_CONNECTION | awk '{print $1}')
    if [[ -z "$src_path" ]]; then
        echo "usage: push <src_path> [dest_path]"
        return
    fi
    echo -e "${BLUE}正在推送 ${src_path} ==> $LOCAL_USER@$host_ip:${dest_path:-$DEST_ROOT}${NC}"
    if [[ "$SYNC_TOOL" == "rsync" ]]; then
    echo "rsync"
        rsync -rlptvzP "$src_path" "$LOCAL_USER@$host_ip:${dest_path:-$DEST_ROOT}"
    else
        scp -r "$src_path" "$LOCAL_USER@$host_ip:${dest_path:-$DEST_ROOT}"
    fi
}


# 拉取数据到车机端
pull_data(){
    local src_path=$1
    local dest_path=$2
    local host_ip=$(echo $SSH_CONNECTION | awk '{print $1}')
    if [[ -z "$dest_path" ]]; then
        echo "usage: pull [src_path] [dest_path]"
        return
    fi
    echo -e "${BLUE}正在拉取 $LOCAL_USER@$host_ip:${src_path} ==> ${dest_path:-$DEST_ROOT}${NC}"
    if [[ "$SYNC_TOOL" == "rsync" ]]; then
        rsync -rlptvzP --protect-args "$LOCAL_USER@$host_ip:$src_path" "${dest_path:-$DEST_ROOT}"
    else
        scp -r "$LOCAL_USER@$host_ip:$src_path" "${dest_path:-$DEST_ROOT}"
    fi
}


# 修复硬盘损坏
fix_disk(){
    stop_service disk
    local target_device=$(blkid -L $DISK_LABEL | head -n 1)
    if [[ -z "$target_device" ]]; then
        echo -e "${RED}错误：找不到标签为 [$DISK_LABEL] 的硬盘，无法修复！${NC}"
        return
    fi
    echo -e "${YELLOW}正在尝试修复硬盘: $target_device ...${NC}"
    sudo fsck.ext4 -yf $target_device
    if [[ $? -eq 0 ]]; then
        start_service
    else
        echo -e "${RED}[$target_device] 修复失败，请重启电源后重试！${NC}"
    fi
}


# 清理内盘数据
clean_cache(){
    stop_service
    echo -e "${GREEN}正在清理缓存：$CACHE ${NC}"
    sudo rm -rf $CACHE
    start_service
}


# 清理包和缓存
clean_pkg(){
    local package=$1
    package="${package#mdrive_}"
    package="${package#mdrive}"
    if [[ -z "$package" ]]; then
        package="mdrive"
    else
        package="mdrive_${package}"
    fi
    echo -e "${GREEN}正在卸载包并清理缓存：$VMC_CACHE/$package ${NC}"
    vmc uninstall $package
    sudo rm -rf $VMC_SOFTWARE/$package
}


clean_all(){
    echo -e "${YELLOW}即将卸载所有 mdrive 相关组件并清理缓存...${NC}"
    local components=("mdrive" "conf" "map" "dep" "model")
    for comp in "${components[@]}"; do
        clean_pkg "$comp"
    done
    echo -e "${GREEN}所有组件清理完成！${NC}"
}

dispatch() {
    local cmd=$1
    shift
    case "$cmd" in
        "init")
            nopasswd
            cli_init
            ;;
        "check")
            check_status "$@"
            ;;
        "status")
            status_service "$@"
            ;;
        "start")
            start_service
            ;;
        "stop")
            stop_service "$@"
            ;;
        "restart")
            stop_service
            start_service
            ;;
        "log")
            watch_log "$@"
            ;;
        "install")
            if [[ -n "$1" ]]; then
                fuzzy_install "$1"
            else
                get_version
                sync_version
            fi
            ;;
        "remove")
            if [[ -n $1 ]]; then
                echo "usage: remove [pkg_name|all]"
            elif [[ "$1" == "all" ]]; then
                clean_all
            else
                clean_pkg "$@"
            fi
            ;;
        "vmc list")
            vmc list
            ;;
        "push")
            push_data "$@"
            ;;
        "pull")
            pull_data "$@"
            ;;
        "fixdisk")
            fix_disk
            ;;
        "clean")
            clean_cache
            ;;
        "exit"|"q")
            exit 0
            ;;
        "")
            :
            ;;
        *)
            echo -e "${RED}未知命令: $cmd${NC}"
            usage
            ;;
    esac
}

# 保留2000行历史
if [[ $(wc -l < "$HISTFILE") -gt 1000 ]]; then
    sed -i ':a;$q;N;1001,$D;ba' "$HISTFILE" 2>/dev/null
fi
history -r "$HISTFILE"
if [[ -n "$1" ]]; then
    INSIDE_MD="false"
    dispatch "$@"
else
    INSIDE_MD="true"
    usage
    check_status
    while true; do
        read -re -p "$PROMPT" input
        [[ -z "$input" ]] && continue
        history -s "$input"
        history -w "$HISTFILE"
        read -r cmd args <<< "$input"
        dispatch "$cmd" $args
    done
fi
