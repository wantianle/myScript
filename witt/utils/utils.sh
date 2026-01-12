#!/usr/bin/env bash
# =========================================================
# utils.sh - Bash 通用工具库
# =========================================================

[ -n "${__LOGGER_SH_LOADED__:-}" ] && return 0
__LOGGER_SH_LOADED__=1

# -------- 时间戳 --------
LOG_SHOW_TIME="${LOG_SHOW_TIME:-0}"
log_prefix() {
    if [ "$LOG_SHOW_TIME" = "1" ]; then
        printf "[%s] " "$(date "+%Y-%m-%d %H:%M:%S")"
    fi
}

# -------- 颜色定义（仅在 TTY 时启用） --------
NC='\033[0m'
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'

if [ ! -t 1 ]; then
    RED= GREEN= YELLOW= BLUE= NC=
fi

# -------- 日志级别 --------
log_info() {
    printf "${GREEN}%s[INFO] %s${NC}\n" "$(log_prefix)" "$*"
}

log_warnning() {
    printf "${YELLOW}%s[WARN] %s${NC}\n" "$(log_prefix)" "$*"
}

log_error() {
    printf "${RED}%s[ERROR] %s${NC}\n" "$(log_prefix)" "$*"
}

log_DEBUG() {
    printf "${BLUE}%s[DEBUG] %s${NC}\n" "$(log_prefix)" "$*"
}


# -------- 错误处理函数 --------
failure() {
    local script=$1
    local lineno=$2
    local msg=$3
    log_error "${script}退出状态码: $?"
    log_error "命令在第 ${lineno} 行发生错误: ${msg}"
}

