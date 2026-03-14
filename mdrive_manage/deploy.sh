#!/usr/bin/env bash

# =================配置区域=================
REMOTE_HOST="ad.minieye.tech"
REMOTE_USER="nvidia"
LOCAL_SCRIPT="./md.sh"
# 待部署的软件包列表 (空格分隔)
DEB_FILES=(
    "rsync_3.1.3-8ubuntu0.9_arm64.deb" "fzf_0.29.0-1ubuntu0.1_arm64.deb"
)
# 代码内预设端口 (如果为空则运行时提示输入)
PRESET_PORTS=(6163 6165)
# PRESET_PORTS=()

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# =================功能函数=================

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
log_err()  { echo -e "${RED}[ERROR]${NC} $1"; }

# 结果统计统计
declare -a SUCCESS_LIST=()
declare -a FAIL_LIST=()

deploy_software() {
    local port=$1
    log_info "[$port] 正在部署软件包..."
    for deb in "${DEB_FILES[@]}"; do
        if [[ ! -f "$deb" ]]; then
            log_err "本地找不到文件: $deb"
            return 1
        fi
        scp -P "$port" "$deb" "${REMOTE_USER}@${REMOTE_HOST}:~/" && \
        ssh -p "$port" -t "${REMOTE_USER}@${REMOTE_HOST}" "sudo dpkg -i ~/$deb && rm ~/$deb"
        [[ $? -ne 0 ]] && return 1
    done
    return 0
}

deploy_script() {
    local port=$1
    log_info "[$port] 正在部署 md.sh..."
    if [[ ! -f "$LOCAL_SCRIPT" ]]; then
        log_err "本地找不到 $LOCAL_SCRIPT"
        return 1
    fi
    scp -P "$port" "$LOCAL_SCRIPT" "${REMOTE_USER}@${REMOTE_HOST}:~/" && \
    ssh -p "$port" "${REMOTE_USER}@${REMOTE_HOST}" "chmod +x ~/md.sh && ~/md.sh init"
    return $?
}

# =================逻辑主流程=================

# 1. 确定端口列表
if [ ${#PRESET_PORTS[@]} -gt 0 ]; then
    PORTS=("${PRESET_PORTS[@]}")
    log_info "使用预设端口: ${PORTS[*]}"
else
    echo -e "${YELLOW}请输入目标端口号 (空格分隔，例如 6171 6173):${NC}"
    read -r -a PORTS
fi

if [ ${#PORTS[@]} -eq 0 ]; then
    log_err "未指定端口，退出。"
    exit 1
fi

# 2. 菜单选择
echo -e "\n${BLUE}请选择部署任务:${NC}"
echo "1) 仅部署软件包"
echo "2) 仅部署 md.sh 脚本"
echo "3) 全部部署"
echo "q) 退出"
read -r -p "请输入选项 [1-3/q]: " opt

case $opt in
    1|2|3) ;;
    *) log_info "退出。"; exit 0 ;;
esac

# 3. 循环执行
for p in "${PORTS[@]}"; do
    echo -e "\n${YELLOW}>>>>>> 正在处理端口: $p <<<<<<${NC}"

    # 测试连接性 (超时 3 秒)
    if ! nc -z -w 3 "$REMOTE_HOST" "$p" &>/dev/null; then
        log_err "无法连接到 $REMOTE_HOST:$p (端口不通或超时)"
        FAIL_LIST+=("$p (连接失败)")
        continue
    fi

    STATUS=0
    if [[ "$opt" == "1" || "$opt" == "3" ]]; then
        deploy_software "$p" || STATUS=1
    fi

    if [[ "$STATUS" -eq 0 && ("$opt" == "2" || "$opt" == "3") ]]; then
        deploy_script "$p" || STATUS=1
    fi

    if [[ "$STATUS" -eq 0 ]]; then
        log_ok "端口 $p 部署成功"
        SUCCESS_LIST+=("$p")
    else
        log_err "端口 $p 部署过程中出现异常"
        FAIL_LIST+=("$p (部署异常)")
    fi
done

# 4. 最终统计
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
