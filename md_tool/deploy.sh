#!/usr/bin/env bash

# 配置
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOC1_IP="192.168.10.2"
SOC2_IP="192.168.10.3"
# WAN_DOMAIN="192.168.16.104"
WAN_DOMAIN="ad.minieye.tech"
REMOTE_USER="nvidia"
# 备选 sudo 密码（按顺序尝试，都失败则交互式输入）
SUDO_PASSWORDS=("mini!@#123.com" "nvidia")
LOCAL_SCRIPT="$DIR/md.sh"
bindir="$DIR/bin"
SSH_OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR)

# 待部署的软件包列表
DEB_FILES=(
    "rsync_3.1.3-8ubuntu0.9_arm64.deb" "fzf_0.29.0-1ubuntu0.1_arm64.deb" "less_551-1_arm64.deb"
)

# 颜色
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
log_err()  { echo -e "${RED}[ERROR]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARNING]${NC} $1"; }

# 免密自检
check_ssh() {
    local host=$1 port=$2
    ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
        -p "$port" "${REMOTE_USER}@${host}" exit 0 2>/dev/null
}

# 结果统计
declare -a SUCCESS_LIST=()
declare -a FAIL_LIST=()

# 探测远端 sudo 密码（逐个尝试预设密码，命中后缓存跳过后续主机试错）
sudo_pass_discover() {
    local host=$1 port=$2
    local found=""

    # 先试上次命中过的密码
    if [[ -n "${SUDO_PASS_CACHED:-}" ]]; then
        if echo "$SUDO_PASS_CACHED" | ssh "${SSH_OPTS[@]}" -p "$port" "${REMOTE_USER}@${host}" \
            "sudo -S true" 2>/dev/null; then
            echo -e "${GREEN}[OK]${NC}   sudo 密码匹配 (缓存)" >&2
            echo "$SUDO_PASS_CACHED"
            return 0
        fi
        echo -e "${YELLOW}[WARNING]${NC}   缓存密码失效，重新探测..." >&2
    fi

    for pw in "${SUDO_PASSWORDS[@]}"; do
        if echo "$pw" | ssh "${SSH_OPTS[@]}" -p "$port" "${REMOTE_USER}@${host}" \
            "sudo -S true" 2>/dev/null; then
            found="$pw"
            break
        fi
    done
    if [[ -n "$found" ]]; then
        SUDO_PASS_CACHED="$found"
        echo -e "${GREEN}[OK]${NC}   sudo 密码匹配" >&2
        echo "$found"
        return 0
    fi
    echo -e "${YELLOW}[WARNING]${NC}   预设密码均不匹配" >&2
    while true; do
        read -rsp "  请输入 ${REMOTE_USER}@${host} sudo 密码: " found
        echo "" >&2
        if [[ -z "$found" ]]; then
            log_err "  密码不能为空"
            continue
        fi
        if echo "$found" | ssh "${SSH_OPTS[@]}" -p "$port" "${REMOTE_USER}@${host}" \
            "sudo -S true" 2>/dev/null; then
            echo -e "${GREEN}[OK]${NC}   sudo 密码验证通过" >&2
            break
        fi
        log_err "  sudo 密码验证失败，请重试"
    done
    SUDO_PASS_CACHED="$found"
    echo "$found"
}

# ============================================================
# 共享辅助函数
# ============================================================
# 校验所有 DEB_FILES 本地存在
local_verify_deb_files() {
    for deb in "${DEB_FILES[@]}"; do
        if [[ ! -f "$bindir/$deb" ]]; then
            log_err "本地找不到文件: $deb"
            return 1
        fi
    done
}

# 上传所有 DEB_FILES 到远端 /tmp/md-tool/
remote_upload_debs() {
    local host=$1 port=$2
    for deb in "${DEB_FILES[@]}"; do
        log_info "  上传 $deb ..."
        scp "${SSH_OPTS[@]}" -P "$port" "$bindir/$deb" "${REMOTE_USER}@${host}:/tmp/md-tool/" || return 1
    done
}

# 远端执行 chmod + md.sh init（含 soc2 密码注入）
remote_run_init() {
    local host=$1 port=$2 sudo_pass=$3
    echo "$sudo_pass" | ssh "${SSH_OPTS[@]}" -p "$port" "${REMOTE_USER}@${host}" \
        "cat > /tmp/md-tool/.soc2_pass && chmod 600 /tmp/md-tool/.soc2_pass" || true
    echo "$sudo_pass" | ssh "${SSH_OPTS[@]}" -p "$port" -t "${REMOTE_USER}@${host}" \
        "sudo -S bash -c 'chmod +x /tmp/md-tool/md.sh && HOME=/home/nvidia USER=nvidia MDRIVE_SOC2_PASS_FILE=/tmp/md-tool/.soc2_pass /tmp/md-tool/md.sh init && rm -f /tmp/md-tool/.soc2_pass'" || return 1
}

# ============================================================
# 部署函数
# ============================================================
deploy_software() {
    local host=$1 port=$2
    log_info "[$host:$port] 正在部署软件包..."

    local_verify_deb_files || return 1
    ssh "${SSH_OPTS[@]}" -p "$port" "${REMOTE_USER}@${host}" "mkdir -p /tmp/md-tool" || return 1
    remote_upload_debs "$host" "$port" || return 1

    local sudo_pass
    sudo_pass=$(sudo_pass_discover "$host" "$port")
    [[ -z "$sudo_pass" ]] && return 1

    local deb_paths=()
    for deb in "${DEB_FILES[@]}"; do
        deb_paths+=("/tmp/md-tool/$deb")
    done
    echo "$sudo_pass" | ssh "${SSH_OPTS[@]}" -p "$port" -t "${REMOTE_USER}@${host}" \
        "sudo -S bash -c 'dpkg -i ${deb_paths[*]} && rm ${deb_paths[*]}'" || return 1

    return 0
}

deploy_script() {
    local host=$1 port=$2
    log_info "[$host:$port] 正在部署 md.sh..."
    if [[ ! -f "$LOCAL_SCRIPT" ]]; then
        log_err "本地找不到 $LOCAL_SCRIPT"
        return 1
    fi
    ssh "${SSH_OPTS[@]}" -p "$port" "${REMOTE_USER}@${host}" "mkdir -p /tmp/md-tool" || return 1
    scp "${SSH_OPTS[@]}" -P "$port" "$LOCAL_SCRIPT" "${REMOTE_USER}@${host}:/tmp/md-tool/" || return 1

    local sudo_pass
    sudo_pass=$(sudo_pass_discover "$host" "$port")
    [[ -z "$sudo_pass" ]] && return 1
    remote_run_init "$host" "$port" "$sudo_pass"
}

deploy_all() {
    local host=$1 port=$2
    log_info "[$host:$port] 正在部署软件包 + md.sh..."

    local_verify_deb_files || return 1
    if [[ ! -f "$LOCAL_SCRIPT" ]]; then
        log_err "本地找不到 $LOCAL_SCRIPT"
        return 1
    fi

    ssh "${SSH_OPTS[@]}" -p "$port" "${REMOTE_USER}@${host}" "mkdir -p /tmp/md-tool" || return 1
    remote_upload_debs "$host" "$port" || return 1
    log_info "  上传 md.sh ..."
    scp "${SSH_OPTS[@]}" -P "$port" "$LOCAL_SCRIPT" "${REMOTE_USER}@${host}:/tmp/md-tool/" || return 1

    local sudo_pass
    sudo_pass=$(sudo_pass_discover "$host" "$port")
    [[ -z "$sudo_pass" ]] && return 1

    echo "$sudo_pass" | ssh "${SSH_OPTS[@]}" -p "$port" "${REMOTE_USER}@${host}" \
        "cat > /tmp/md-tool/.soc2_pass && chmod 600 /tmp/md-tool/.soc2_pass" || true

    local deb_paths=()
    for deb in "${DEB_FILES[@]}"; do
        deb_paths+=("/tmp/md-tool/$deb")
    done
    echo "$sudo_pass" | ssh "${SSH_OPTS[@]}" -p "$port" -t "${REMOTE_USER}@${host}" \
        "sudo -S bash -c 'chmod +x /tmp/md-tool/md.sh && HOME=/home/nvidia USER=nvidia MDRIVE_SOC2_PASS_FILE=/tmp/md-tool/.soc2_pass /tmp/md-tool/md.sh init && dpkg -i ${deb_paths[*]} && rm -f ${deb_paths[*]} /tmp/md-tool/.soc2_pass'" || return 1

    return 0
}

# ============================================================
# 1. 选择模式
# ============================================================
echo -e "${BLUE}===============================================${NC}"
echo -e "  ${GREEN}1)${NC} 局域网部署 (SOC1: ${YELLOW}.10.2${NC}, SOC2: ${YELLOW}.10.3${NC})"
echo -e "  ${GREEN}2)${NC} 公网部署     (域名: ${YELLOW}${WAN_DOMAIN}${NC})"
echo -e "${BLUE}===============================================${NC}"
read -rp "  请选择模式 [1/2]: " MODE
echo ""

if [ "$MODE" != "1" ] && [ "$MODE" != "2" ]; then
    log_err "无效模式，请输入 1 或 2"
    exit 1
fi

declare -a TARGET_HOSTS=()
declare -a TARGET_PORTS=()
declare -a TARGET_LABELS=()

if [ "$MODE" == "1" ]; then
    TARGET_HOSTS=("$SOC1_IP" "$SOC2_IP")
    TARGET_PORTS=(22 22)
    TARGET_LABELS=("soc1" "soc2")
else
    echo -e "${YELLOW}请输入目标端口号 (空格分隔，例如 6171 6173):${NC}"
    read -r -a PORTS
    if [ ${#PORTS[@]} -eq 0 ]; then
        log_err "未指定端口，退出。"
        exit 1
    fi
    for p in "${PORTS[@]}"; do
        TARGET_HOSTS+=("$WAN_DOMAIN")
        TARGET_PORTS+=("$p")
        TARGET_LABELS+=("$p")
    done
fi

# ============================================================
# 2. 免密自检
# ============================================================
log_info "免密自检..."
no_key_count=0
for i in "${!TARGET_HOSTS[@]}"; do
    host="${TARGET_HOSTS[$i]}"
    port="${TARGET_PORTS[$i]}"
    label="${TARGET_LABELS[$i]}"
    if check_ssh "$host" "$port"; then
        log_ok "  $label 免密已就绪"
    else
        log_warn "  $label 免密未配置，请先运行 ssh.sh"
        ((no_key_count++))
    fi
done
if [ "$no_key_count" -gt 0 ]; then
    echo ""
    log_warn "$no_key_count 个目标未配置免密，部署可能失败"
fi
echo ""

# ============================================================
# 3. 菜单选择
# ============================================================
echo -e "${BLUE}请选择部署任务:${NC}"
echo "  1) 仅部署软件包"
echo "  2) 仅部署 md.sh 脚本"
echo "  3) 全部部署"
echo "  q) 退出"
read -r -p "  请输入选项 [1-3/q]: " opt

case $opt in
    1|2|3) ;;
    *) log_info "退出。"; exit 0 ;;
esac

# ============================================================
# 4. 循环执行
# ============================================================
for i in "${!TARGET_HOSTS[@]}"; do
    host="${TARGET_HOSTS[$i]}"
    port="${TARGET_PORTS[$i]}"
    label="${TARGET_LABELS[$i]}"

    echo -e "\n${YELLOW}>>>>>> 正在处理: $label ($host:$port) <<<<<<${NC}"

    if ! command -v nc &>/dev/null; then
        log_warn "未安装 nc，跳过连通性检测"
    elif ! nc -z -w 3 "$host" "$port" &>/dev/null; then
        log_err "$label 端口不可达 ($host:$port)"
        FAIL_LIST+=("$label (连接失败)")
        continue
    fi

    STATUS=0
    if [[ "$opt" == "1" ]]; then
        deploy_software "$host" "$port" || STATUS=1
    elif [[ "$opt" == "2" ]]; then
        deploy_script "$host" "$port" || STATUS=1
    else
        deploy_all "$host" "$port" || STATUS=1
    fi

    if [[ "$STATUS" -eq 0 ]]; then
        log_ok "$label 部署成功"
        SUCCESS_LIST+=("$label")
    else
        log_err "$label 部署过程中出现异常"
        FAIL_LIST+=("$label (部署异常)")
    fi
done

# ============================================================
# 5. 最终统计
# ============================================================
echo -e "\n==============================================="
echo -e "${BLUE}部署任务总结:${NC}"
echo -e "${GREEN}成功数量: ${#SUCCESS_LIST[@]} [${SUCCESS_LIST[*]}]${NC}"
if [ ${#FAIL_LIST[@]} -gt 0 ]; then
    echo -e "${RED}失败数量: ${#FAIL_LIST[@]}${NC}"
    for fail in "${FAIL_LIST[@]}"; do
        echo -e "  - $fail"
    done
fi
echo "==============================================="
