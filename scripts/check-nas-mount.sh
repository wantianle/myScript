#!/bin/bash
#
# 遍历 nvidia@192.168.21.51-58，端口 222 和 333，共 16 个目标
# 检测 media-nas.mount 是否正常，不正常则重启相关服务

set -euo pipefail

PASS='mini!@#123.com'
MAIN_PORTS=(222 322)
START_IP=51
END_IP=57

log()    { printf '[%(%Y-%m-%d %H:%M:%S)T] %s\n' -1 "$*"; }
ok()     { log "OK   $*"; }
fail()   { log "FAIL $*"; }

check_and_fix() {
    local ip="$1" port="$2"
    local target="nvidia@${ip}"
    local state rc

    # 检查 media-nas.mount 状态（0=active, 非0=非active/超时）
    state=$(sshpass -p "$PASS" ssh \
        -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null \
        -o ConnectTimeout=5 \
        -o ServerAliveInterval=3 \
        -p "$port" \
        "$target" \
        "systemctl is-active media-nas.mount" 2>/dev/null) || rc=$?
    state="${state:-}"

    if [[ "$state" == "active" ]]; then
        ok "${target}:${port} media-nas.mount is active"
        return 0
    fi

    # SSH 不可达，直接跳过重启
    if [[ -z "$state" ]]; then
        fail "${target}:${port} unreachable (timeout), skip restart"
        return 0
    fi

    # inactive / failed — 执行重启
    fail "${target}:${port} state=${state}, restarting..."

    sshpass -p "$PASS" ssh \
        -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null \
        -o ConnectTimeout=5 \
        -o ServerAliveInterval=3 \
        -p "$port" \
        "$target" \
        "echo '$PASS' | sudo -S systemctl restart add-nas-route.service && \
         echo '$PASS' | sudo -S systemctl restart media-nas.mount" 2>/dev/null || true

    # 二次确认
    sleep 1
    state=$(sshpass -p "$PASS" ssh \
        -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null \
        -o ConnectTimeout=5 \
        -o ServerAliveInterval=3 \
        -p "$port" \
        "$target" \
        "systemctl is-active media-nas.mount" 2>/dev/null) || true
    state="${state:-}"

    if [[ "$state" == "active" ]]; then
        ok "${target}:${port} restored → active"
    else
        fail "${target}:${port} still NOT active (state=${state:-timeout})"
    fi
}

# ---- main ----
log "Targets: 192.168.21.${START_IP}-${END_IP} x ports ${MAIN_PORTS[*]}"

for ((i=START_IP; i<=END_IP; i++)); do
    for port in "${MAIN_PORTS[@]}"; do
        check_and_fix "192.168.21.${i}" "$port"
    done
done

log "Done."
