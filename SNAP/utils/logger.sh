#!/usr/bin/env bash
# =========================================================
# logger.sh - 通用 Bash 日志库
# =========================================================

# -------- 基本保护，防止重复 source --------
[ -n "${__LOGGER_SH_LOADED__:-}" ] && return 0
__LOGGER_SH_LOADED__=1

# -------- 时间戳 --------
LOG_SHOW_TIME="${LOG_SHOW_TIME:-1}"
log_prefix() {
    if [ "$LOG_SHOW_TIME" = "1" ]; then
        printf "[%s] " "$(target_date "+%Y-%m-%d %H:%M:%S")"
    fi
}

# -------- 颜色定义（仅在 TTY 时启用） --------
NC='\033[0m'
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
GRAY='\033[0;90m'

if [ ! -t 1 ]; then
    RED= GREEN= YELLOW= BLUE= GRAY= NC=
fi

# -------- 日志级别 --------
log_info() {
    printf "${GREEN}%s[INFO] %s${NC}\n" "$(log_prefix)" "$*"
}

log_warn() {
    printf "${YELLOW}%s[WARN] %s${NC}\n" "$(log_prefix)" "$*"
}

log_error() {
    printf "${RED}%s[ERROR] %s${NC}\n" "$(log_prefix)" "$*"
}

log_step() {
    printf "${BLUE}%s[STEP] %s${NC}\n" "$(log_prefix)" "$*"
}

log_debug() {
    [ "${DEBUG:-0}" = "1" ] || return 0
    printf "${GRAY}%s[DEBUG] %s${NC}\n" "$(log_prefix)" "$*"
}
