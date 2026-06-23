#!/usr/bin/env bash

# 配置
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOC1_IP="192.168.10.2"
SOC2_IP="192.168.10.3"
WAN_DOMAIN="ad.minieye.tech"
REMOTE_USER="nvidia"
LOCAL_SCRIPT="$DIR/md.sh"
bindir="$DIR/bin"

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

deploy_software() {
    local host=$1 port=$2
    log_info "[$host:$port] 正在部署软件包..."
    for deb in "${DEB_FILES[@]}"; do
        if [[ ! -f "$bindir/$deb" ]]; then
            log_err "本地找不到文件: $deb"
            return 1
        fi
        scp -P "$port" "$bindir/$deb" "${REMOTE_USER}@${host}:~/" || return 1
        ssh -p "$port" -t "${REMOTE_USER}@${host}" "sudo dpkg -i ~/$deb && rm ~/$deb" || return 1
    done
    return 0
}

deploy_script() {
    local host=$1 port=$2
    log_info "[$host:$port] 正在部署 md.sh..."
    if [[ ! -f "$LOCAL_SCRIPT" ]]; then
        log_err "本地找不到 $LOCAL_SCRIPT"
        return 1
    fi
    scp -P "$port" "$LOCAL_SCRIPT" "${REMOTE_USER}@${host}:~/" || return 1
    ssh -p "$port" -t "${REMOTE_USER}@${host}" "chmod +x ~/md.sh && ~/md.sh init" || return 1
}

# ============================================================
# 1. 选择模式
# ============================================================
echo -e "${BLUE}===============================================${NC}"
echo -e "  ${GREEN}1)${NC} 局域网部署 (SOC1: ${YELLOW}.10.2${NC}, SOC2: ${YELLOW}.10.3${NC})"
echo -e "  ${GREEN}2)${NC} 公网部署     (域名: ${YELLOW}ad.minieye.tech${NC})"
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
        TARGET_LABELS+=("soc$p")
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

    if ! nc -z -w 3 "$host" "$port" &>/dev/null; then
        if ! command -v nc &>/dev/null; then
            log_warn "未安装 nc，跳过连通性检测"
        else
            log_err "$label 端口不可达 ($host:$port)"
            FAIL_LIST+=("$label (连接失败)")
            continue
        fi
    fi

    STATUS=0
    if [[ "$opt" == "1" || "$opt" == "3" ]]; then
        deploy_software "$host" "$port" || STATUS=1
    fi
    if [[ "$STATUS" -eq 0 && ("$opt" == "2" || "$opt" == "3") ]]; then
        deploy_script "$host" "$port" || STATUS=1
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
