#!/usr/bin/env bash

#region ==================== HEADER ====================

# 颜色配置
RED='\033[1;31m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
NC='\033[0m'
# 避免 ssh 把本机 zh_CN.UTF-8 转发到车端（车端无此 locale 会导致 setlocale 警告）
export LC_ALL=C
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
SOC2_IP="192.168.10.3"
SSH_OPTS=(
    -o ConnectTimeout=2
    -o ServerAliveInterval=2
    -o ServerAliveCountMax=2
    -o StrictHostKeyChecking=no
    -o UserKnownHostsFile=/dev/null
    -o LogLevel=ERROR
    -i "$KEY_PATH"
)
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


md::_ensure_ssh_opts() {
    if declare -p SSH_OPTS >/dev/null 2>&1 && [[ $(declare -p SSH_OPTS) == declare\ -a* ]]; then
        return 0
    fi
    SSH_OPTS=(
        -o ConnectTimeout=2
        -o ServerAliveInterval=2
        -o ServerAliveCountMax=2
        -o StrictHostKeyChecking=no
        -o UserKnownHostsFile=/dev/null
        -o LogLevel=ERROR
        -i "$KEY_PATH"
    )
}


usage() {
    local prefix="md "
    echo -e "${BLUE}Usage:${NC}"
    echo -e "  ${prefix}<command> [arguments]"
    echo -e "  <>必选  []可选  ()可简写"
    echo ""
    echo -e "${BLUE}-- 初始化 --${NC}"
    printf "  ${YELLOW}%-45s${NC}  %s\n" "init"                       "部署后初始化免密并安装工具到系统"
    echo ""
    echo -e "${BLUE}-- 状态检查 --${NC}"
    printf "  ${YELLOW}%-45s${NC}  %s\n" "check"                      "检查网络/时间/硬盘/设备状态"
    printf "  ${YELLOW}%-45s${NC}  %s\n" "status [1(soc1)|2(soc2)]"   "查看双端 mdrive 服务状态，可指定单端"
    echo ""
    echo -e "${BLUE}-- 服务控制 --${NC}"
    printf "  ${YELLOW}%-45s${NC}  %s\n" "start/stop/restart [1|2]"   "启停双端 mdrive 服务，可用 1(soc1)/2(soc2) 指定单端"
    printf "  ${YELLOW}%-45s${NC}  %s\n" "log [1(soc1)|2(soc2)]"      "查看最近 5 分钟单端服务日志(带过滤跟踪，缺省=soc1)"
    printf "  ${YELLOW}%-45s${NC}  %s\n" "c(channel) [1(soc1)|2(soc2)]" "查看 soc1/soc2 DDS 消息"
    printf "  ${YELLOW}%-45s${NC}  %s\n" "m(module) [action soc 模块...]" "无参数: fzf 交互管理模块; 有参数: 单端启停模块"
    printf "  ${YELLOW}%-45s${NC}  %s\n" "mod <start|stop|restart> <1|2> <模块名>" "直接启停单个模块(与 m 参数形态一致)"
    printf "  ${YELLOW}%-45s${NC}  %s\n" "record [on]|<off>"          "开启/关闭 soc2 Recorder"
    echo ""
    echo -e "${BLUE}-- 版本管理 --${NC}"
    printf "  ${YELLOW}%-45s${NC}  %s\n" "upgrade"                    "自检并升级到最新版本"
    printf "  ${YELLOW}%-45s${NC}  %s\n" "install [version]"          "编辑版本信息批量升级，或直接指定单包版本"
    printf "  ${YELLOW}%-45s${NC}  %s\n" "rb(rollback) [version] [name]" "按版本关键字回滚; '-' 占位不限版本, '=name' 精确包名"
    printf "  ${YELLOW}%-45s${NC}  %s\n" ""                           "  例: rb 1.1.1 cve / rb - =mdrive / rb - cve"
    printf "  ${YELLOW}%-45s${NC}  %s\n" "remote <add|del|list>"      "管理本地包对应的远程分支"
    printf "  ${YELLOW}%-45s${NC}  %s\n" ""                           "  remote add <name> [branch|-] [platform] / remote del <name>"
    echo ""
    echo -e "${BLUE}-- 硬盘与导出 --${NC}"
    printf "  ${YELLOW}%-45s${NC}  %s\n" "umount"                     "停止服务并安全弹出硬盘"
    printf "  ${YELLOW}%-45s${NC}  %s\n" "e(export)"                  "交互式选择 bag/log 文件并导出到本地电脑"
    echo ""
    echo -e "${BLUE}-- 帮助 --${NC}"
    printf "  ${YELLOW}%-45s${NC}  %s\n" "help|-h|--help"             "显示本帮助"
    echo ""
}

#endregion

#region ==================== MODULES =====================

#region -------------------  sys 系统层 ------------------

# 免密处理
sys::_sudoers_content() {
    cat <<'EOF'
# Managed by md_tool. Keep NOPASSWD limited to recurring vehicle operations.
Cmnd_Alias MDRIVE_SERVICE = /usr/bin/systemctl start mdrive.service, /usr/bin/systemctl stop mdrive.service, /usr/bin/systemctl restart mdrive.service, /usr/bin/systemctl restart media-data.mount
Cmnd_Alias MDRIVE_LOG = /usr/bin/journalctl -eu mdrive.service *
Cmnd_Alias MDRIVE_SUPERVISOR = /usr/bin/supervisorctl status, /usr/bin/supervisorctl start *, /usr/bin/supervisorctl stop *, /usr/bin/supervisorctl restart *, /usr/local/bin/supervisorctl status, /usr/local/bin/supervisorctl start *, /usr/local/bin/supervisorctl stop *, /usr/local/bin/supervisorctl restart *
Cmnd_Alias MDRIVE_DISK = /usr/bin/umount -l /media/data, /bin/umount -l /media/data, /usr/bin/mount /dev/* /media/data, /bin/mount /dev/* /media/data, /usr/sbin/e2fsck -yf /dev/*, /sbin/e2fsck -yf /dev/*
Cmnd_Alias MDRIVE_VMC = /usr/bin/chown -R nvidia\:nvidia /mnt/ufs_data/project/.vmc/softwares/*, /bin/chown -R nvidia\:nvidia /mnt/ufs_data/project/.vmc/softwares/*, /usr/bin/chown -R nvidia\:nvidia /mdrive/.vmc/softwares/*, /bin/chown -R nvidia\:nvidia /mdrive/.vmc/softwares/*
nvidia ALL=(root) NOPASSWD: MDRIVE_SERVICE, MDRIVE_LOG, MDRIVE_SUPERVISOR, MDRIVE_DISK, MDRIVE_VMC
EOF
}

sys::_install_local_sudoers() {
    local tmp status
    tmp=$(mktemp) || return 1

    if ! sys::_sudoers_content > "$tmp"; then
        rm -f "$tmp"
        return 1
    fi

    sudo visudo -cf "$tmp" >/dev/null && sudo cp "$tmp" "$SUDO_PATH" && sudo chmod 0440 "$SUDO_PATH"
    status=$?
    rm -f "$tmp"
    return "$status"
}

sys::_install_remote_sudoers() {
    local encoded remote_cmd soc2_pass
    encoded=$(sys::_sudoers_content | base64 | tr -d '\n') || return 1

    if [[ -n "${MDRIVE_SOC2_PASS_FILE:-}" && -f "$MDRIVE_SOC2_PASS_FILE" ]]; then
        soc2_pass=$(cat "$MDRIVE_SOC2_PASS_FILE")
        remote_cmd=$(cat <<EOF
tmp=\$(mktemp) || exit 1
printf '%s' '$encoded' | base64 -d > "\$tmp" || { rm -f "\$tmp"; exit 1; }
echo '$soc2_pass' | sudo -S visudo -cf "\$tmp" >/dev/null && \
echo '$soc2_pass' | sudo -S cp "\$tmp" "$SUDO_PATH" && \
echo '$soc2_pass' | sudo -S chmod 0440 "$SUDO_PATH"
status=\$?
rm -f "\$tmp"
exit \$status
EOF
)
    else
        remote_cmd=$(cat <<EOF
tmp=\$(mktemp) || exit 1
printf '%s' '$encoded' | base64 -d > "\$tmp" || { rm -f "\$tmp"; exit 1; }
sudo visudo -cf "\$tmp" >/dev/null && sudo cp "\$tmp" "$SUDO_PATH" && sudo chmod 0440 "$SUDO_PATH"
status=\$?
rm -f "\$tmp"
exit \$status
EOF
)
    fi

    ssh "${SSH_OPTS[@]}" -t "$USER@$SOC2_IP" "$remote_cmd"
}

sys::nopasswd(){
    # 免密ssh
    mkdir -p "$(dirname "$KEY_PATH")"
    chmod 700 "$(dirname "$KEY_PATH")"
    if [ ! -f "$KEY_PATH" ]; then
        echo "未发现密钥，正在生成默认密钥..."
        ssh-keygen -t ed25519 -f "$KEY_PATH" -N ""
    fi

    # 确保证钥权限正确（sudo bash -c 下可能 root 所有）
    chmod 700 "$(dirname "$KEY_PATH")" 2>/dev/null
    chmod 600 "$KEY_PATH" "$KEY_PATH.pub" 2>/dev/null
    chown "$USER:$USER" "$KEY_PATH" "$KEY_PATH.pub" "$(dirname "$KEY_PATH")" 2>/dev/null || true
    # 修复 ~/.ssh 下所有文件权限（sudo bash -c 下可能 root 所有）
    chown -R "$USER:$USER" "$(dirname "$KEY_PATH")" 2>/dev/null || true

    if ssh_err=$(ssh "${SSH_OPTS[@]}" -o BatchMode=yes "$USER@$SOC2_IP" exit 2>&1); then
        log_ok "soc2 SSH 免密已配置"
    else
        echo "推送公钥到soc2：$USER@$SOC2_IP..."
        if [[ -n "${MDRIVE_SOC2_PASS_FILE:-}" && -f "$MDRIVE_SOC2_PASS_FILE" ]]; then
            # 非交互式：通过 SSH_ASKPASS 自动填写密码
            local _askpass
            _askpass=$(mktemp)
            printf '#!/bin/bash\ncat %s\n' "$MDRIVE_SOC2_PASS_FILE" > "$_askpass"
            chmod +x "$_askpass"
            DISPLAY=dummy SSH_ASKPASS="$_askpass" ssh-copy-id \
                -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
                -i "${KEY_PATH}.pub" "$USER@$SOC2_IP" </dev/null || {
                rm -f "$_askpass"
                log_err "推送公钥到 soc2 失败，请检查密码或网络"
                log_err "提示: 请手工执行 ssh-copy-id $USER@$SOC2_IP 确认 soc2 可达且密码正确后重跑 md init"
                return 1
            }
            rm -f "$_askpass"
        else
            if ! ssh-copy-id -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i "${KEY_PATH}.pub" "$USER@$SOC2_IP"; then
                log_err "推送公钥到 soc2 失败，请检查 soc1 -> soc2 网络和 nvidia 用户密码"
                log_err "提示: 请手工执行 ssh-copy-id $USER@$SOC2_IP 确认 soc2 可达且密码正确后重跑 md init"
                return 1
            fi
        fi
        if ! ssh_error=$(ssh "${SSH_OPTS[@]}" -o BatchMode=yes "$USER@$SOC2_IP" exit 2>&1); then
            echo "$ssh_error" >&2
            log_err "soc2 SSH 免密验证失败"
            return 1
        fi
        log_ok "soc2 SSH 免密配置完成"
    fi

    touch "$CONFIG_PATH"
    chmod 600 "$CONFIG_PATH"
    if ! grep -q "Host soc2" "$CONFIG_PATH"; then
        echo "配置 soc2 快捷登录：ssh soc2"
        cat << EOF >> "$CONFIG_PATH"
# Orin SOC2 快捷登录
Host soc2
    HostName $SOC2_IP
    User $USER
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
    LogLevel ERROR
EOF
    fi

    # 受限免密 sudo。sudoers 自身安装仍需要一次 sudo 授权。
    echo "配置 soc1 受限免密 sudo..."
    if sys::_install_local_sudoers; then
        log_ok "soc1 受限 sudo 免密配置完成"
    else
        log_err "soc1 受限 sudo 免密配置失败"
        log_err "提示: 手动执行 sudo visudo -f $SUDO_PATH 检查语法后重跑 md init"
        return 1
    fi
    echo "配置 soc2 受限免密 sudo..."
    if sys::_install_remote_sudoers; then
        log_ok "soc2 sudo 免密配置完成"
    else
        log_err "soc2 sudo 免密配置失败"
        log_err "提示: 手动执行 sudo visudo -f $SUDO_PATH 检查语法后重跑 md init"
        return 1
    fi
}


# 初始化命令行工具
sys::init(){
    local script_path
    script_path=$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null)
    if [[ -z "$script_path" || ! -f "$script_path" ]]; then
        log_err "无法定位当前脚本路径: ${BASH_SOURCE[0]}"
        return 1
    fi

    # 安装二进制命令
    if [[ "$script_path" != "/usr/local/bin/md" ]]; then
        if ! sudo cp "$script_path" /usr/local/bin/md; then
            log_err "初始化失败，无法复制当前脚本: $script_path"
            return 1
        fi
    fi
    if sudo chmod +x /usr/local/bin/md; then
        log_ok "工具已安装到 /usr/local/bin/md"
        # 清理历史遗留的 tag 软链（tag 功能已弃用）
        sudo rm -f /usr/local/bin/tag
    else
        log_err "初始化失败，无法设置 /usr/local/bin/md 可执行权限"
        return 1
    fi

    # 安装自动补全脚本
    local completion_file="/etc/bash_completion.d/md"
    local completion_tmp
    echo "正在安装自动补全..."
    completion_tmp=$(mktemp) || {
        log_err "无法创建自动补全临时文件"
        return 1
    }
    {
        declare -f _md_completions
        printf "complete -F _md_completions md\n"
    } > "$completion_tmp"
    if sudo cp "$completion_tmp" "$completion_file" && sudo chmod 0644 "$completion_file"; then
        rm -f "$completion_tmp"
    else
        rm -f "$completion_tmp"
        log_err "自动补全安装失败: $completion_file"
        return 1
    fi

    log_ok "初始化完成！请执行 'source $completion_file' 或重启终端生效。"
    echo -e "试试输入: ${GREEN}md [TAB][TAB]${NC}"
}


sys::_resolve_export_user() {
    local input_user

    if ssh -n -q "${EXPORT_SSH_OPTS[@]}" "mini@$EXPORT_LOCAL_IP" exit 2>/dev/null; then
        EXPORT_PC_USER="mini"
        log_info "本地回传用户: $EXPORT_PC_USER"
        return 0
    fi

    printf "请输入本地电脑 SSH 用户名: "
    read -r input_user
    if [[ ! "$input_user" =~ ^[A-Za-z0-9._-]+$ ]]; then
        log_err "用户名格式非法: $input_user"
        return 1
    fi

    EXPORT_PC_USER="$input_user"
    return 0
}


sys::_is_private_ip() {
    local ip=$1
    [[ "$ip" =~ ^10\. ]] && return 0
    [[ "$ip" =~ ^192\.168\. ]] && return 0
    [[ "$ip" =~ ^172\.(1[6-9]|2[0-9]|3[0-1])\. ]] && return 0
    return 1
}


sys::_is_localhost_ip() {
    local ip=$1
    [[ "$ip" == "127.0.0.1" || "$ip" == "localhost" || "$ip" == "::1" ]]
}


sys::_is_listening_port() {
    local port=$1
    if command -v ss >/dev/null 2>&1; then
        ss -tln 2>/dev/null | awk '{print $4}' | grep -Eq "(^|:|\\])${port}$"
        return $?
    fi
    netstat -tuln 2>/dev/null | grep -q ":${port}"
}


sys::_current_session_pids() {
    local pid=$$ ppid
    while [[ -n "$pid" && "$pid" != "1" && -r "/proc/$pid/stat" ]]; do
        printf "%s\n" "$pid"
        ppid=$(awk '{print $4}' "/proc/$pid/stat" 2>/dev/null)
        [[ -z "$ppid" || "$ppid" == "$pid" ]] && break
        pid=$ppid
    done
}


sys::_current_reverse_tunnel_ports() {
    command -v ss >/dev/null 2>&1 || return 0

    local pids=()
    local line pid addr port
    mapfile -t pids < <(sys::_current_session_pids)
    [[ ${#pids[@]} -eq 0 ]] && return 0

    while IFS= read -r line; do
        for pid in "${pids[@]}"; do
            [[ "$line" == *"pid=$pid,"* ]] || continue
            addr=$(awk '{print $4}' <<< "$line")
            port=${addr##*:}
            [[ "$port" =~ ^[0-9]+$ ]] && printf "%s\n" "$port"
            break
        done
    done < <(ss -H -tlnp 2>/dev/null) | sort -n -u
}


sys::prepare_export_ssh() {
    EXPORT_SSH_PORT=22
    EXPORT_LOCAL_IP=""
    EXPORT_PC_USER=""
    local ssh_source_ip reverse_port
    local reverse_ports=()

    ssh_source_ip=$(echo "${SSH_CONNECTION:-}" | awk '{print $1}' | tr -d '\r')
    if [[ -n "$ssh_source_ip" ]] && sys::_is_private_ip "$ssh_source_ip" && ! sys::_is_localhost_ip "$ssh_source_ip"; then
        log_info "当前 SSH 来源为局域网地址，回传当前直连电脑 (Target: $ssh_source_ip)..."
        EXPORT_LOCAL_IP="$ssh_source_ip"
        EXPORT_SSH_PORT=22
    else
        mapfile -t reverse_ports < <(sys::_current_reverse_tunnel_ports)
        if [[ ${#reverse_ports[@]} -eq 1 ]]; then
            reverse_port=${reverse_ports[0]}
            log_info "检测到当前 SSH 会话的公网回传端口: 127.0.0.1:$reverse_port"
        else
            log_warn "当前 SSH 来源不是局域网直连，无法唯一识别当前电脑的公网回传隧道"
            log_warn "多人同时操作时，不能自动使用任意 127.0.0.1:端口，否则可能传到同事电脑"
            if [[ ${#reverse_ports[@]} -gt 1 ]]; then
                log_warn "当前 SSH 会话检测到多个回传端口: ${reverse_ports[*]}"
            fi
            printf "请输入你当前电脑建立的回传隧道端口（ssh -R <端口>:localhost:22），输入 q 取消: "
            read -r reverse_port
            if [[ "$reverse_port" == "q" || "$reverse_port" == "Q" || -z "$reverse_port" ]]; then
                log_err "已取消导出；请先为当前电脑建立回传隧道后重试"
                return 1
            fi
        fi
        if [[ ! "$reverse_port" =~ ^[0-9]+$ ]]; then
            log_err "回传端口非法: $reverse_port"
            return 1
        fi
        if (( reverse_port < 1 || reverse_port > 65535 )); then
            log_err "回传端口非法: $reverse_port"
            return 1
        fi
        if ! sys::_is_listening_port "$reverse_port"; then
            log_err "车端本机未监听回传端口: $reverse_port"
            log_err "请确认当前电脑 SSH 连接已带上: -R ${reverse_port}:localhost:22"
            return 1
        fi
        log_info "启用当前会话指定的公网回传端口: 127.0.0.1:$reverse_port"
        EXPORT_LOCAL_IP="127.0.0.1"
        EXPORT_SSH_PORT="$reverse_port"
    fi

    if [[ -z "$EXPORT_LOCAL_IP" ]]; then
        log_err "未检测到本地 SSH 连接 IP"
        log_err "提示: 请通过 ssh 直连(局域网)或带 -R 端口反向隧道登录车端后执行 md export"
        return 1
    fi

    EXPORT_SSH_OPTS=( -p "$EXPORT_SSH_PORT" -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=2 -o LogLevel=ERROR )
    EXPORT_SSH_COPY_OPTS=( -p "$EXPORT_SSH_PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=2 -o LogLevel=ERROR )

    if ! sys::_resolve_export_user; then
        log_err "无法确定本地电脑 SSH 用户名"
        return 1
    fi
    EXPORT_TARGET_LABEL="$EXPORT_PC_USER@$EXPORT_LOCAL_IP"

    if ! ssh -n -q "${EXPORT_SSH_OPTS[@]}" "$EXPORT_PC_USER@$EXPORT_LOCAL_IP" exit 2>/dev/null; then
        log_info "未检测到免密授权，准备配置 (Target: $EXPORT_PC_USER@$EXPORT_LOCAL_IP:$EXPORT_SSH_PORT)..."
        if ssh-copy-id "${EXPORT_SSH_COPY_OPTS[@]}" "$EXPORT_PC_USER@$EXPORT_LOCAL_IP"; then
            log_ok "免密验证通过！"
            if ! ssh -n -q "${EXPORT_SSH_OPTS[@]}" "$EXPORT_PC_USER@$EXPORT_LOCAL_IP" exit 2>/dev/null; then
                log_err "公钥已下发，但免密验证仍失败，请检查目标端 authorized_keys 与 SSH 配置"
                return 1
            fi
        else
            log_err "免密配置未生效（可能是密码错误、目标用户不匹配，或笔记本 SSH 未开启）"
            return 1
        fi
    fi

    sys::prepare_export_dirs
}


sys::prepare_export_dirs() {
    local roots="/media/mdrive_export"
    local prepare_cmd="mkdir -p $roots"
    local fix_cmd='sudo mkdir -p /media && sudo chown "$USER:$USER" /media && mkdir -p /media/mdrive_export'

    if ssh -n "${EXPORT_SSH_OPTS[@]}" "$EXPORT_PC_USER@$EXPORT_LOCAL_IP" "$prepare_cmd" >/dev/null 2>&1; then
        return 0
    fi

    log_warn "本地电脑 /media 无法创建导出目录，准备在本地电脑执行: sudo chown \$USER:\$USER /media"
    log_warn "如果本地电脑提示 sudo 密码，请输入本地电脑用户 $EXPORT_PC_USER 的密码"
    if ssh "${EXPORT_SSH_COPY_OPTS[@]}" -t "$EXPORT_PC_USER@$EXPORT_LOCAL_IP" "$fix_cmd"; then
        log_ok "本地导出目录已准备: /media/mdrive_export"
        return 0
    fi

    log_err "本地导出目录准备失败，请在本地电脑执行: sudo chown \$USER:\$USER /media"
    return 1
}


sys::export_mkdir() {
    local dest=$1
    ssh -n "${EXPORT_SSH_OPTS[@]}" "$EXPORT_PC_USER@$EXPORT_LOCAL_IP" "mkdir -p '$dest'"
}


sys::_safe_cache_root() {
    local cache=${1:-}
    local normalized real

    if [[ -z "$cache" || "$cache" != /* ]]; then
        log_err "拒绝清理非法 MDRIVE_CACHE: ${cache:-<empty>}"
        return 1
    fi

    normalized=${cache%/}
    if [[ "${normalized##*/}" != ".cache" ]]; then
        log_err "拒绝清理非 .cache 目录: $normalized"
        return 1
    fi

    real=$(readlink -f "$normalized" 2>/dev/null)
    if [[ -z "$real" || ! -d "$real" ]]; then
        log_err "MDRIVE_CACHE 不存在或无法解析: $normalized"
        return 1
    fi

    case "$real" in
        "/"|"/home"|"/mnt"|"/media"|"/tmp"|"/var"|"/usr"|"/mdrive_data")
            log_err "拒绝清理高风险目录: $real"
            return 1
            ;;
    esac

    printf "%s\n" "$real"
}


sys::_clean_cache_contents() {
    local scope=$1
    local cache_root target

    cache_root=$(sys::_safe_cache_root "$MDRIVE_CACHE") || return 1
    case "$scope" in
        "data")
            target="$cache_root/data"
            ;;
        "all")
            target="$cache_root"
            ;;
        *)
            log_err "未知清理范围: $scope"
            return 1
            ;;
    esac

    if [[ ! -d "$target" ]]; then
        log_warn "缓存目录不存在，跳过清理: $target"
        return 0
    fi

    log_info "正在清理缓存：$target"
    if find "$target" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +; then
        return 0
    fi

    log_warn "普通权限清理失败，尝试 sudo 清理（此操作不在免密白名单内）"
    sudo find "$target" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
}


# 清理内盘数据
sys::clean(){
    local avail cache_root
    cache_root=$(sys::_safe_cache_root "$MDRIVE_CACHE") || return 1
    avail=$(disk_free_gb "$cache_root")
    if [[ "$avail" -lt 5 ]]; then
        log_warn "系统剩余空间不足 5GB (当前: ${avail}GB)，过低会影响 OTA 版本升级，是否需要清理？(Y/n)"
        read -r confirm
        [[ "$confirm" == "n" || "$confirm" == "N" ]] && return
        sys::_clean_cache_contents data
    fi
}


sys::export() {
    local timestamp
    timestamp=$(date +%m%d_%H%M)
    local local_dest="/media/mdrive_export/${timestamp}"
    sys::prepare_export_ssh || return 1

    # 2. 文件扫描与交互选择
    log_info "正在扫描 $MDRIVE_DATA_ROOT 下的所有可导出内容..."

    local selections
    selections=$(cd -L "$MDRIVE_DATA_ROOT" && find -L . -mindepth 1 -maxdepth 3 -not -path '*/.*' 2>/dev/null | sort | fzf \
        --multi \
        --ansi \
        --layout=reverse \
        --height=95% \
        --header "目标: ${EXPORT_TARGET_LABEL:-$EXPORT_LOCAL_IP}:$EXPORT_SSH_PORT | Tab:勾选 | Ctrl-A:全选 | Enter:确认并导出" \
        --bind "ctrl-a:toggle-all")

    [[ -z "$selections" ]] && { log_warn "已取消操作"; return; }

    local count
    count=$(printf "%s\n" "$selections" | wc -l)
    log_info "开始传输 $count 项内容到 $local_dest"

    if ! sys::export_mkdir "$local_dest"; then
        log_err "本地导出目录创建失败: ${EXPORT_TARGET_LABEL:-$EXPORT_LOCAL_IP}:$local_dest"
        return 1
    fi

    if ! cd -L "$MDRIVE_DATA_ROOT"; then
        log_err "无法进入数据目录: $MDRIVE_DATA_ROOT"
        return 1
    fi

    local failed=false
    while IFS= read -r -u 3 item; do
        [[ -z "$item" ]] && continue
        if ! rsync -avPL -R -e "ssh ${EXPORT_SSH_OPTS[*]}" "$item" "$EXPORT_PC_USER@$EXPORT_LOCAL_IP:$local_dest/" < /dev/null; then
            log_err "传输中断: $item"
            failed=true
        fi
    done 3<<< "$selections"

    if $failed; then
        log_err "部分文件导出失败，请检查本地电脑网络/磁盘空间/路径权限后重试"
        return 1
    fi

    log_ok "导出完成！本地路径: ${EXPORT_TARGET_LABEL:-$EXPORT_LOCAL_IP}:$local_dest"
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
            ssh "${SSH_OPTS[@]}" "$SOC2_IP" "systemctl is-active --quiet mdrive.service"
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
            ssh "${SSH_OPTS[@]}" "$SOC2_IP" "timeout 15 sudo systemctl $action mdrive.service"
            svc::check soc2
            ;;
    esac

}


# 解析 soc 参数(供 start/stop/restart/status): 合法 1/soc1/2/soc2/空(空=双端)。非法打印错误并返回 1
svc::_resolve_soc_arg() {
    local arg=${1:-}
    case "$arg" in
        soc1|1) printf 'soc1\n' ;;
        soc2|2) printf 'soc2\n' ;;
        "") printf 'both\n' ;;
        *)
            log_err "无效 SOC 参数: $arg（仅支持 1/soc1/2/soc2，缺省=双端）" >&2
            return 1
            ;;
    esac
}

# 查看日志
svc::log(){
    case "$1" in
        "soc1"|"1"|"")
            sudo journalctl -eu mdrive.service --since "5 min ago" -f --no-pager | grep --line-buffered -v -E "ptp4l|phc2sys|mdrive_driver_camera"
            ;;
        "soc2"|"2")
            ssh "${SSH_OPTS[@]}" -t "$SOC2_IP" 'sudo journalctl -eu mdrive.service --since "5 min ago" -f --no-pager | grep --line-buffered -v -E "ptp4l|phc2sys|mdrive_driver_camera"'
            ;;
        *)
            log_err "无效 SOC 参数: $1（仅支持 1/soc1/2/soc2，缺省=soc1）"
            return 1
            ;;
    esac
}


# recorder
svc::recorder(){
    local action=${1:-on}
    local supervisor_action action_text avail disk_ready=false

    case "$action" in
        "on")
            supervisor_action="start"
            action_text="启动"
            ;;
        "off")
            supervisor_action="stop"
            action_text="停止"
            ;;
        *)
            usage
            return 1
            ;;
    esac

    if ssh "${SSH_OPTS[@]}" "$SOC2_IP" "timeout 2 mountpoint -q $MOUNT_ROOT"; then
        echo -e "[soc2]硬盘: ${GREEN}Mounted${NC}"
        disk_ready=true
        avail=$(ssh "${SSH_OPTS[@]}" "$SOC2_IP" "df -BG $MOUNT_ROOT 2>/dev/null | awk 'NR==2 {print \$4}' | tr -d 'G'")
        if [[ "$avail" =~ ^[0-9]+$ ]]; then
            if [[ "$avail" -lt 200 ]]; then
                log_warn "soc2 数据盘剩余空间不足 200GB (当前: ${avail}GB)！"
            fi
        else
            log_warn "无法读取 soc2 数据盘剩余空间: $MOUNT_ROOT"
        fi
    else
        log_err "soc2 硬盘未挂载或无法访问: $MOUNT_ROOT"
        log_err "提示: 运行 md check，按提示修复硬盘后再 md record on"
    fi

    if [[ "$action" == "on" && "$disk_ready" != "true" ]]; then
        log_err "拒绝启动 Recorder，请先修复 soc2 数据盘挂载"
        return 1
    fi

    if ssh "${SSH_OPTS[@]}" "$SOC2_IP" "sudo supervisorctl $supervisor_action Recorder 2>/dev/null"; then
        log_ok "soc2 Recorder 已${action_text}"
    else
        log_err "soc2 Recorder ${action_text}失败"
        return 1
    fi
}


svc::channel(){
    case "$1" in
        "soc1"|"1"|"")
            dtop
            ;;
        "soc2"|"2")
            ssh "${SSH_OPTS[@]}" -t "$SOC2_IP" "export MDRIVE_ROOT_DIR='/mdrive' && export MDRIVE_DEP_DIR='/mdrive/mdrive_dep' && source $VMC_SOFTWARE/mdrive/setup.sh && export GLOG_log_dir='${GLOG_log_dir:-/mnt/ufs_data/project/data/log}' && dtop"
            ;;
        *)
            log_err "无效 SOC 参数: $1（仅支持 1/soc1/2/soc2，缺省=soc1）"
            return 1
            ;;
    esac
}

# 执行模块启停操作，返回真实退出码
svc::_run_module_action() {
    local soc=$1 mod=$2 action=$3 rc out
    echo -e "正在对 [$soc] $mod 执行 $action..."
    if [[ "$soc" == "soc1" ]]; then
        out=$(sudo supervisorctl "$action" "$mod" 2>&1); rc=$?
    else
        out=$(ssh "${SSH_OPTS[@]}" "$SOC2_IP" "sudo supervisorctl $action $mod" 2>&1 </dev/null); rc=$?
    fi
    sleep 1
    if (( rc == 0 )); then
        log_ok "[$soc] $mod $action 成功"
    elif (( rc == 255 )); then
        log_err "[$soc] $mod $action 失败: soc2 SSH 连接错误"
    else
        log_err "[$soc] $mod $action 失败: ${out:-未知错误}"
    fi
    return "$rc"
}


# 用法: md m <start|stop|restart> <1(soc1)|2(soc2)> <模块名...>
svc::mod_ctl() {
    local action=$1 soc_arg=$2
    shift 2
    if [[ -z "$action" || -z "$soc_arg" || $# -eq 0 ]]; then
        log_err "用法: md m <start|stop|restart> <1(soc1)|2(soc2)> <模块名...>"
        return 1
    fi
    case "$action" in
        start|stop|restart) ;;
        *)
            log_err "无效操作: $action (仅支持 start/stop/restart)"
            return 1
            ;;
    esac
    local soc
    case "$soc_arg" in
        soc1|1) soc=soc1 ;;
        soc2|2) soc=soc2 ;;
        *)
            log_err "无效 SOC: $soc_arg (1=soc1, 2=soc2)"
            return 1
            ;;
    esac
    local mod fail_count=0
    for mod in "$@"; do
        svc::_run_module_action "$soc" "$mod" "$action" || ((fail_count++))
    done
    return "$fail_count"
}


# 打开模块日志
svc::_open_module_log() {
    local soc=$1 mod=$2 log_type=$3
    local path
    path=$(log_get_path "$soc" "$mod" "$log_type")
    if [[ "$log_type" == "glog" ]]; then
        local exists=false
        if [[ -L "$path" ]]; then
            exists=true
        fi
        if [[ "$exists" == "false" ]]; then
            echo -e "${YELLOW}未匹配到精准日志，请手动选择:${NC}"
            local picked
            picked=$(find "$GLOG_log_dir" -maxdepth 1 -type l -name '*.INFO*' -printf '%f\n' 2>/dev/null | sort | fzf \
                --height=100% \
                --layout=reverse \
                --border \
                --header "--- 日志列表 ---" \
                --info=inline)
            [[ -z "$picked" ]] && return
            path="$GLOG_log_dir/$picked"
        fi
    fi
    if [[ -r "$path" ]]; then
        less -R -S --follow-name +F "$path"
    else
        sudo less -R -S --follow-name +F "$path"
    fi
}


# 模块动作执行器
# 用法: svc::mod_handler "<fzf_line>" <action>
svc::mod_handler() {
    md::_ensure_ssh_opts

    local raw_line=$1 action=$2
    local line
    # Strip ANSI escape sequences
    line=$(echo "$raw_line" | sed 's/\x1b\[[0-9;]*m//g')

    local soc mod state tail
    # fetch_combined/supervisorctl 输出为空格分隔: [socN] mod STATE tail
    line=$(echo "$line" | tr -s ' ')
    read -r soc mod state tail <<< "$line"
    soc="${soc#\[}"; soc="${soc%\]}"
    [[ -z "$soc" || -z "$mod" ]] && return

    case "$action" in
        "glog"|"sv")  svc::_open_module_log "$soc" "$mod" "$action" ;;
        "start"|"stop"|"restart")
            svc::_run_module_action "$soc" "$mod" "$action"
            return $?
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
        bin_path=$(echo "$raw_cmd" | grep -oP '/mdrive/bin/[^ ]+' | head -n 1)
        bin_name="${bin_path##*/}"
        [[ -z "$bin_name" ]] && bin_name="${mod,,}"
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
    md::_ensure_ssh_opts

    local s1 s2
    s1=$(sudo supervisorctl status 2>/dev/null | awk '{print "soc1 " $0}')
    s2=$(ssh "${SSH_OPTS[@]}" "$SOC2_IP" "sudo supervisorctl status" 2>/dev/null | awk '{print "soc2 " $0}')
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

export -f md::_ensure_ssh_opts fetch_combined
export SOC2_IP RED GREEN YELLOW BLUE NC KEY_PATH

svc::module() {
    if ! command -v fzf &> /dev/null; then
        log_warn "请先安装 fzf..."
        return 1
    fi
    local last_query=""
    while true; do
        local result key action fzf_query
        result=$(fetch_combined | fzf \
            --ansi \
            --multi \
            --height 95% \
            --reverse \
            --bind "tab:toggle+down" \
            --header $'Tab:多选(批量启停)  Ctrl-R:刷新  Esc:退出\nEnter:当前行sv日志  Alt-Enter:开发日志  Alt-S/X/R:启/停/重启(单行=当前行, 多选=批量)' \
            --expect=enter,alt-enter,alt-s,alt-x,alt-r,esc \
            --print-query \
            --query "$last_query" \
            --nth 2,3 \
            --bind "ctrl-r:reload(fetch_combined)")

        [[ -z "$result" ]] && return

        # fzf 输出结构: [查询串, 按键, 选中项...]
        fzf_query=$(echo "$result" | head -1)
        key=$(echo "$result" | sed -n '2p')
        last_query="$fzf_query"

        case "$key" in
            esc) return ;;
            enter) action=sv ;;
            alt-enter) action=glog ;;
            alt-s) action=start ;;
            alt-x) action=stop ;;
            alt-r) action=restart ;;
            *) continue ;;
        esac

        # Log viewing: only process the first item (focused)
        if [[ "$action" == "sv" || "$action" == "glog" ]]; then
            local sel_count log_line
            sel_count=$(echo "$result" | tail -n +3 | grep -c '[^[:space:]]' || true)
            log_line=$(echo "$result" | sed -n '3p')
            if [[ -n "$log_line" ]]; then
                if (( sel_count > 1 )); then
                    log_warn "已选 $sel_count 项，日志仅打开选中项中列表序第 1 项"
                fi
                local clean_line soc mod
                clean_line=$(echo "$log_line" | sed 's/\x1b\[[0-9;]*m//g' | tr -s ' ')
                read -r soc mod _ <<< "$clean_line"
                soc="${soc#\[}"; soc="${soc%\]}"
                if [[ -n "$soc" && -n "$mod" ]]; then
                    log_info "日志: [$soc] $mod"
                fi
                svc::mod_handler "$log_line" "$action"
            fi
            continue
        fi

        # Batch start/stop/restart: process all selected items
        local count=0 fail=0
        while IFS= read -r line; do
            [[ -z "$line" ]] && continue
            ((count++))
            svc::mod_handler "$line" "$action" || ((fail++))
        done < <(echo "$result" | tail -n +3)
        if (( count > 1 )); then
            if (( fail > 0 )); then
                log_warn "批量${action}: $count 个模块 (失败 $fail 个)"
            else
                echo "批量${action}: $count 个模块"
            fi
        fi
        # Loop back → fzf re-opens with refreshed data
    done
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


# 取路径可用空间 (GB)，失败返回空
disk_free_gb() {
    df -BG "$1" 2>/dev/null | awk 'NR==2 {print $4}' | tr -d 'G'
}


# 取路径已用百分比，失败返回空
disk_used_pct() {
    df -h "$1" 2>/dev/null | awk 'NR==2 {print $5}' | tr -d '%'
}


disk::usage() {
    local name=$1
    local path=$2
    local disk_usage
    disk_usage=$(disk_used_pct "$path")
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
    local retry=0
    while mountpoint -q "$MOUNT_ROOT" && (( ++retry <= 5 )); do
        sudo umount -l "$MOUNT_ROOT" 2>/dev/null || sleep 1
    done
    if mountpoint -q "$MOUNT_ROOT"; then
        log_err "卸载 $MOUNT_ROOT 失败，请手动检查"
        log_err "提示: 运行 md check 查看硬盘状态，或先 md start 恢复服务后再试"
        return 1
    fi
    ssh "${SSH_OPTS[@]}" "$SOC2_IP" "sudo umount -l $MOUNT_ROOT 2>/dev/null"
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

    ssh "${SSH_OPTS[@]}" "$SOC2_IP" "mountpoint -q $MOUNT_ROOT"
    local res=$?
    if [[ $res -ne 0 ]]; then
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

    if ! ssh "${SSH_OPTS[@]}" "$SOC2_IP" "timeout 2 stat -t $MOUNT_ROOT/data >/dev/null 2>&1"; then
        log_err "挂载目录内容无法访问 $MOUNT_ROOT"
        return 4
    fi

    if grep "$MOUNT_ROOT" /proc/mounts | grep -q " ro,"; then
        log_err "文件系统已降级为 [只读] soc1:${MOUNT_ROOT}"
        return 5
    fi

    if ssh "${SSH_OPTS[@]}" "$SOC2_IP" "grep $MOUNT_ROOT /proc/mounts | grep -q ' ro,'"; then
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
    avail=$(disk_free_gb "$MDRIVE_CACHE")
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
        ssh "${SSH_OPTS[@]}" "$SOC2_IP" "sudo systemctl restart media-data.mount"
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
        sys::_clean_cache_contents all || return 1
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
            local name=${2:-} branch=${3:-} platform=${4:-}
            if [[ -z "$name" || "$name" == *" "* || "$name" == "#"* ]]; then
                log_err "用法: md remote add <name> <branch|-> [platform]"
                return 1
            fi
            [[ -z "$branch" ]] && branch="-"
            local new_entry="$name $branch $platform"
            if [[ -f "$REMOTE_CONFIG" ]] && grep -Fxq "$new_entry" "$REMOTE_CONFIG"; then
                log_warn "配置 [$new_entry] 已存在"
            else
                echo "$new_entry" >> "$REMOTE_CONFIG"
                log_ok "已添加: $new_entry"
            fi
            ;;
        "del")
            local name=${2:-}
            if [[ -z "$name" ]]; then
                log_err "请指定要删除的包名"
                return 1
            fi
            if [[ ! -f "$REMOTE_CONFIG" ]] || ! awk -v name="$name" '$1==name {found=1} END{exit !found}' "$REMOTE_CONFIG"; then
                log_err "远程配置中不存在包名: $name"
                return 1
            fi
            local tmp
            tmp=$(mktemp) || return 1
            awk -v name="$name" '$1 != name' "$REMOTE_CONFIG" > "$tmp" && mv "$tmp" "$REMOTE_CONFIG"
            rm -f "$tmp"
            log_ok "分支 [$name] 远程配置已删除"
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


# 询问确认，回车/Y 继续返回0，n/N 取消返回1
vmc::_confirm() {
    local msg=$1
    local confirm
    read -r -p "$msg [Y/n]: " confirm
    [[ "$confirm" == "n" || "$confirm" == "N" ]] && return 1
    return 0
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
        grep -F "name: ${pkg_name}," | \
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


# 安装前回收包目录属主：旧包目录内若有 root 残留文件，vmc 删旧换新会 permission denied
vmc::_prep_pkg_dir() {
    local pkg_name=$1
    local user
    user=$(id -un 2>/dev/null || echo nvidia)
    local candidate real
    [[ -n "$pkg_name" ]] || return 0
    for candidate in \
        "${VMC_HOME:-$HOME/.vmc}/softwares/$pkg_name" \
        "$HOME/.vmc/softwares/$pkg_name" \
        "/mnt/ufs_data/project/.vmc/softwares/$pkg_name" \
        "/mdrive/.vmc/softwares/$pkg_name"; do
        real=$(readlink -f "$candidate" 2>/dev/null)
        if [[ -n "$real" && -d "$real" ]]; then
            if sudo chown -R "$user:$user" "$real" 2>/dev/null; then
                log_info "[$pkg_name] 已回收包目录属主: $real"
            else
                log_warn "[$pkg_name] 包目录属主回收失败(可能不在免密白名单)，将以交互方式执行"
                sudo chown -R "$user:$user" "$real" || return 1
            fi
            return 0
        fi
    done
    # 目录不存在 = 全新安装，无需回收
    return 0
}


vmc::_install_pkg() {
    local pkg_name=$1
    local version=$2
    local rc

    # 旧包目录可能有 root 残留文件，先回收属主避免 vmc 删旧失败
    vmc::_prep_pkg_dir "$pkg_name"

    if [[ $pkg_name == "mdrive_map" ]]; then
        vmc install -n "$pkg_name" -v "$version" --deps
    else
        vmc install -n "$pkg_name" -v "$version"
    fi
    rc=$?

    if [[ $rc -ne 0 ]]; then
        return 1
    fi

    # vmc 可能报错但仍返回 0，通过实际安装版本来验证
    local installed_ver
    installed_ver=$(vmc::_get_current_ver "$pkg_name")
    if [[ -z "$installed_ver" || "$installed_ver" != "$version" ]]; then
        log_warn "[$pkg_name] vmc 返回成功但版本验证失败: 期望 $version, 实际 ${installed_ver:-未安装}"
        return 1
    fi

    return 0
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
            while true; do
                read -r -p "请选择序号 (跳过请输入 s, 默认 0): " choice
                choice=${choice:-0}
                if [[ "$choice" == "s" || "$choice" == "S" ]]; then
                    break
                fi
                if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 0 && choice < ${#options[@]} )); then
                    final_queue+=("${options[$choice]}")
                    break
                fi
                log_err "无效序号: $choice，有效范围 0-$(( ${#options[@]} - 1 ))，或输入 s 跳过"
            done
        fi
    done

    # 安装
    [[ ${#final_queue[@]} -eq 0 ]] && { log_warn "未选择任何安装项"; return 0; }
    vmc::_confirm "确定执行升级" || return 0
    svc::manage stop soc1
    svc::manage stop soc2
    local failed=false
    for q in "${final_queue[@]}"; do
        local n v
        n=$(echo "$q" | cut -d':' -f1)
        v=$(echo "$q" | cut -d':' -f2)
        log_info "正在安装 [$n] $v ..."
        if vmc::_install_pkg "$n" "$v"; then
            log_ok "[$n] 安装成功"
        else
            log_err "[$n] 安装失败"
            failed=true
        fi
    done

    if $failed; then
        log_err "存在安装失败项，已停止自动启动服务，请检查后手动处理"
        log_warn "执行 md start 恢复双端服务运行"
        return 1
    fi

    vmc list
    svc::manage start soc1
    svc::manage start soc2
}


# 获取版本信息
vmc::install(){
    if flow::pre; then
        log_info "是否继续升级版本？('y'或回车继续，其他键退出)"
        read -r ans
        if [[ "$ans" != "y" && "$ans" != "" ]]; then
            log_warn "已取消升级"
            return 1
        fi
    else
        log_info "是否继续升级版本？('f'强制继续，其他键退出)"
        read -r ans
        if [[ "$ans" != "f" ]]; then
            log_warn "已取消升级"
            return 1
        fi
    fi
    local tmp_file
    tmp_file=$(mktemp)
    log_info "即将打开 vi 编辑器，请粘贴版本信息，保存并退出后生效..."
    sleep 1
    {
        echo "# 每行指定一个要升级的包，未列出的包保持不动。格式: 包名: 版本号"
        echo "# 示例:"
        echo "#   mdrive_conf: 1.0.0"
        echo "#   mdrive_map:  1.1.1"
        echo ""
        echo "# 当前已安装版本(参考，去掉 # 并改成目标版本即生效):"
        vmc list 2>/dev/null | awk '{print "#   " $1 ": " $2}' | tr -d '()'
    } > "$tmp_file"
    vi "$tmp_file"
    input_text=$(< "$tmp_file")
    log_info "更新以下包版本："
    echo "$input_text"
    rm -f "$tmp_file"
    # 正则提取清洗
    _extract() {
    local pattern=$1
    # 包名后需跟非标识符字符或行尾, 避免 mdrive 误匹配 mdrive_conf 行
    echo "$input_text" | grep -iE "^[[:space:]]*(${pattern})([^_a-zA-Z0-9]|$)" | head -n 1 | sed -r "
        s/^[[:space:]]*(${pattern})[^_a-zA-Z0-9]?//i; # 删掉 key 本身及紧随的分隔符(忽略大小写)
        s/^[[:space:]:：]*//;     # 删掉可能存在的冒号或空格
        s/^[[:space:]\"（(]*//;   # 删掉开头可能残留的空格、引号、左括号
        s/[[:space:]\"）)]*$//;   # 删掉结尾可能残留的空格、引号、右括号
        s/\r//g                   # 删掉 Windows 换行符
    "
    }
    local failed=false installed=false stopped=false
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
        installed=true
        if [[ "$stopped" != "true" ]]; then
            # 确认确有包要安装后才停服（避免 vi 未写有效版本时白停）
            svc::manage stop soc1
            svc::manage stop soc2
            stopped=true
        fi
        if vmc::_install_pkg "$name" "$version"; then
            log_ok "[$name] 安装成功"
        else
            log_err "[$name] 安装失败"
            failed=true
        fi
    done

    if [[ "$installed" != "true" ]]; then
        log_warn "未提取到任何可安装版本"
        return 1
    fi
    if $failed; then
        log_err "存在安装失败项，已停止自动启动服务，请检查后手动处理"
        log_warn "执行 md start 恢复双端服务运行"
        return 1
    fi

    svc::manage start soc1
    svc::manage start soc2
}


# 模糊更新单个包版本
# 用法: vmc::finstall <version> [pkg_name]
#  pkg_name 可选：由调用方明确指定包名时直接使用（如 rollback 从 fzf 选中行带出），
#  避免多个包同名版本时按 version 反查命错包。
vmc::finstall() {
    local version=$1
    local pkg_name=${2:-}
    if [[ -z "$pkg_name" ]]; then
        # 优先匹配 version 字段以搜索词开头的行（避免 mdrive 误匹配 mdrive_conf）
        pkg_name=$(vmc fsearch -v "$version" | awk -F', ' -v v="$version" '
            /^name:/ {
                n=""; r=""
                for (i=1; i<=NF; i++) {
                    if ($i ~ /^name: /) { sub(/^name: /, "", $i); n=$i }
                    if ($i ~ /^version:/) { sub(/^version:[ ]*/, "", $i); r=$i }
                }
                if (r == v) { print n; exact=1; exit }
                if (index(r, v "-") == 1 || index(r, v ".") == 1) { if (!pref) { pref=n } }
                if (!last) { last=n }
            }
            END { if (!exact) { if (pref) print pref; else if (last) print last } }
        ')
    fi
    if [[ -n "$pkg_name" ]]; then
        log_info "下载安装 [${pkg_name}] ${version}..."
        if vmc::_install_pkg "$pkg_name" "$version"; then
            log_ok "安装成功，手动重启服务或继续升级..."
        else
            log_err "[$pkg_name] 安装失败"
            return 1
        fi
    else
        log_err "未找到适用于 Orin 平台的包，请检查版本是否正确！"
        return 1
    fi
}


# 回滚版本
vmc::rollback() {
    local pkg_name=""
    local search_v=""
    local name_kw=""
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
        name_kw=${2:-}
    fi
    # 命令行版本关键字 "-" 表示不限版本
    [[ "$search_v" == "-" ]] && search_v=""

    log_info "正在搜索历史版本..."
    local versions_list
    # 双参数检索: $1=版本关键字("-"=不限), $2=包名关键字(带 "=" 前缀=精确包名, 否则子串模糊)
    # remote 配置分支的 pkg_name 等价于精确模式: 只展示该包
    local exact_col="" name_for_search=""
    if [[ -n "$pkg_name" ]]; then
        # remote 配置分支: 精确包名
        name_for_search=$pkg_name
        exact_col=$pkg_name
    elif [[ "$name_kw" == "="* ]]; then
        # CLI "=name": 精确包名, 剥掉 "=" 前缀传给 -n (子串可命中), 再按第 4 列精确过滤
        name_for_search="${name_kw#=}"
        exact_col=$name_for_search
    else
        # CLI 模糊模式: 包名子串, 不做第 4 列精确过滤, 让 fzf 展示所有子串命中的包
        name_for_search=$name_kw
    fi
    versions_list=$(vmc fsearch ${name_for_search:+-n "$name_for_search"} ${search_v:+-v "$search_v"} -i 100 --verbose | awk '
        /^\[Index:/ {
            if (version) print time " | " version " | " platform " | " name;
            name=""; version=""; time=""; platform="";
            # 仅当 Index 行内直接带有 name: 时才就地提取包名，否则交给下面的 Name: 行填充
            if ($0 ~ /[Nn]ame:/) {
                tmp=$0; sub(/^.*[Nn]ame:[ ]*/, "", tmp); sub(/[,}].*$/, "", tmp); name=tmp
            }
        }
        /^[ \t]*[Nn]ame:/ {
            if (name == "") {
                tmp=$0; sub(/^[ \t]*[Nn]ame:[ \t]*/, "", tmp); sub(/[,}].*$/, "", tmp); name=tmp
            }
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
        END { if (version) print time " | " version " | " platform " | " name; }
    ' | sort -r)

    # 精确模式(remote 配置包名 / CLI "=name")下 vmc -n 仍是子串匹配, 按展示列表第 4 列精确过滤;
    # CLI 模糊模式(name_kw 不带 "=")不做第 4 列过滤, 保留所有子串命中的包供 fzf 区分挑选
    if [[ -n "$exact_col" ]]; then
        versions_list=$(echo "$versions_list" | awk -F ' \\| ' -v pkg="$exact_col" '$4 == pkg')
    fi

    if [[ -z "$versions_list" ]]; then
        log_err "[ver:${search_v:-*}, name:${name_for_search:-*}] 未搜索到任何远程版本"
        log_err "提示: 换更短版本关键字，或先用 md remote list 确认分支与包名"
        return 1
    fi
    local selected_line
    selected_line=$(echo "$versions_list" | grep -E "$VMC_PLATFORM|any" | fzf \
        --ansi \
        --header "发布时间            |  远程版本号          |  平台      |  包名 (ver: ${search_v:-*}, name: ${name_for_search:-*})" \
        --layout=reverse \
        --height=100%)

    [[ -z "$selected_line" ]] && { log_warn "取消回滚"; return; }
    # 从选中行提取 版本 和 真实包名(第4列)，包名必须透传给 finstall，
    # 否则同名版本(如 mdrive_cve/mdrive_dep 都有 1.1.2)会按 version 反查命错包
    local selected_ver selected_pkg
    selected_ver=$(echo "$selected_line" | awk -F ' \| ' '{print $2}' | tr -d '[:space:]')
    selected_pkg=$(echo "$selected_line" | awk -F ' \| ' '{print $4}' | tr -d '[:space:]')

    log_warn "确定回滚 [$selected_pkg] 到版本: $selected_ver ?"
    vmc::_confirm "确认执行" || return

    # 停止服务
    svc::manage stop soc1
    svc::manage stop soc2
    sys::clean
    if ! vmc::finstall "$selected_ver" "$selected_pkg"; then
        log_warn "回滚失败，服务已停止，执行 md start 恢复运行"
        return 1
    fi
}

#endregion

#region ==================== WORKFLOW ====================

flow::pre() {
    local check_pass=true
    log_info "----------- Network Check -----------"

    printf "%-41s" "[网络] SOC2 :"
    if ssh "${SSH_OPTS[@]}" -q "$SOC2_IP" exit; then
        echo -e "${GREEN}正常${NC}"
    else
        echo -e "${RED}断开${NC}"
        log_err "请检查 soc2 供电/网线 (ping $SOC2_IP)，恢复后重试"
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
                printf "%-40s %-18b %s\n" "[设备] $name [$ip]:" "${GREEN}在线${NC}" "[延迟: ${avg_ms}ms | 丢包: ${loss_display}%]" > "$result_file"
            else
                local reason="未知错误"
                local reason_display
                [[ "$ping_res" =~ "Unreachable" ]] && reason="网络不可达"
                [[ "$ping_res" =~ "100% packet loss" ]] && reason="请求超时"
                reason_display="[${reason}]"
                printf "%-40s %-18b %s\n" "[设备] $name [$ip]:" "${RED}离线${NC}" "$reason_display" > "$result_file"
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
    ts2=$(ssh "${SSH_OPTS[@]}" "$SOC2_IP" date +%s)
    t2_str=$(ssh "${SSH_OPTS[@]}" "$SOC2_IP" "date +'%Y-%m-%d %H:%M:%S'")

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
    opts="init check umount upgrade install rollback rb stop start restart status log c channel m module mod record remote export e"

    case "$prev" in
        stop|start|restart|status|log|c|channel)
            COMPREPLY=( $(compgen -W "soc1 soc2 1 2" -- "$cur") )
            return 0
            ;;
        mod|m|module)
            COMPREPLY=( $(compgen -W "start stop restart" -- "$cur") )
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
    local cmd=$1 _umount_confirm
    shift
    case "$cmd" in
        "init")
            sys::nopasswd || return 1
            sys::init
            ;;
        "check")
            flow::pre
            ;;
        "start"|"stop"|"restart")
            local soc
            soc=$(svc::_resolve_soc_arg "${1:-}") || return 1
            if [[ "$soc" == "both" ]]; then
                svc::manage "$cmd" soc1
                svc::manage "$cmd" soc2
            else
                svc::manage "$cmd" "$soc"
            fi
            ;;
        "status")
            local soc
            soc=$(svc::_resolve_soc_arg "${1:-}") || return 1
            if [[ "$soc" == "both" ]]; then
                svc::check soc1
                svc::check soc2
            else
                svc::check "$soc"
            fi
            ;;
        "log")
            svc::log "$@"
            ;;
        "module"|"m")
            if (( $# == 0 )); then
                svc::module
            else
                svc::mod_ctl "$@"
            fi
            ;;
        "mod")
            svc::mod_ctl "$@"
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
            if [[ -n "$1" ]]; then
                vmc::_confirm "将停止双端 mdrive 服务并安装 $1（服务不会自动重启）" || return
                svc::manage stop soc1
                svc::manage stop soc2
                sys::clean
                if ! vmc::finstall "$1"; then
                    log_warn "安装失败，服务已停止，执行 md start 恢复运行"
                    return 1
                fi
            else
                sys::clean
                vmc::install || return 1
            fi
            vmc list
            ;;
        "umount")
            log_warn "此操作将: ① 停止双端 mdrive 服务 ② 卸载数据盘 $MOUNT_ROOT"
            log_warn "如硬盘正被 Recorder 写入，当前录制会中断"
            read -r -p "输入 y 确认弹出硬盘 [y/N]: " _umount_confirm
            [[ "$_umount_confirm" == "y" || "$_umount_confirm" == "Y" ]] || { log_warn "已取消"; return; }
            svc::manage stop soc1
            svc::manage stop soc2
            disk::umount
            ;;
        "export"|"e")
            sys::export
            ;;
        "-h"|"--help"|"help")
            usage
            ;;
        *)
            log_err "未知命令: $cmd"
            usage
            ;;
    esac
}


main(){
    if [[ -z $1 ]]; then
        usage
    else
        dispatch "$@"
    fi
}

main "$@"
#endregion
#endregion
