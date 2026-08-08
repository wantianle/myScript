#!/bin/bash
#
# 向 192.168.21.402-407 的 soc1(222) / soc2(322) 部署 /etc/nvsciipc.cfg
# 新文件: ./nvsciipc.cfg

set -euo pipefail

PASS='mini!@#123.com'
START_IP=52
END_IP=57
PORTS=(222 322)
SRC_FILE="$(dirname "$0")/nvsciipc.cfg"
REMOTE_PATH="/etc/nvsciipc.cfg"

log()    { printf '[%(%Y-%m-%d %H:%M:%S)T] %s\n' -1 "$*"; }
ok()     { log "OK   $*"; }
fail()   { log "FAIL $*"; }

[[ -f "$SRC_FILE" ]] || { fail "source file not found: $SRC_FILE"; exit 1; }

deploy_one() {
    local ip="$1" port="$2"
    local target="nvidia@${ip}"

    # 1. scp to /tmp
    if ! sshpass -p "$PASS" scp \
        -P "$port" \
        -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null \
        -o ConnectTimeout=5 \
        -o LogLevel=ERROR \
        "$SRC_FILE" \
        "${target}:/tmp/nvsciipc.cfg" 2>/dev/null; then
        fail "${target}:${port} scp failed"
        return 1
    fi

    # 2. backup + sudo mv; keep system configuration ownership and mode
    if ! echo "$PASS" | timeout 15 sshpass -p "$PASS" ssh \
        -p "$port" \
        -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null \
        -o ConnectTimeout=5 \
        -o ServerAliveInterval=3 \
        -o LogLevel=ERROR \
        "$target" \
        "sudo -S cp -p '$REMOTE_PATH' '${REMOTE_PATH}.bak' 2>/dev/null; \
         sudo -S mv /tmp/nvsciipc.cfg '$REMOTE_PATH' && \
         sudo -S chown root:root '$REMOTE_PATH' && \
         sudo -S chmod 0644 '$REMOTE_PATH' && \
         ls -la '$REMOTE_PATH'" 2>/dev/null; then
        fail "${target}:${port} deploy failed"
        return 1
    fi

    ok "${target}:${port}"
    return 0
}

# ---- main ----
log "Deploying nvsciipc.cfg ($(wc -c < "$SRC_FILE") bytes) to 192.168.21.${START_IP}-${END_IP}"

total=0 good=0 bad=0

for ((i=START_IP; i<=END_IP; i++)); do
    ip="192.168.21.${i}"
    for port in "${PORTS[@]}"; do
        total=$((total + 1))
        if deploy_one "$ip" "$port"; then
            good=$((good + 1))
        else
            bad=$((bad + 1))
        fi
    done
done

log "Done. ${good}/${total} OK, ${bad} failed"
