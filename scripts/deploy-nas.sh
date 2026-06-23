#!/usr/bin/env bash
###############################################################################
# 一键部署 NAS 路由 + 挂载到所有 SoC
# 目标: 8 台机器 x 2 SoC = 16 个目标
#   soc1: ssh port 222
#   soc2: ssh port 322
#   常规:   via 192.168.10.1 src 192.168.10.2 / 192.168.10.3
#   53号机: via 192.168.9.1  src 192.168.9.2  / 192.168.9.3
# 用法: ./deploy-nas.sh
# 原理: 先 scp 脚本到远程, 再 ssh 执行, 密码通过管道传给 sudo -S
###############################################################################
set -o pipefail

SSH_USER="nvidia"
SSH_PASS="mini!@#123.com"
SUDO_PASS="mini!@#123.com"
BASE_IP_START=51
BASE_IP_END=58
SOC1_PORT=222
SOC2_PORT=322
TIMEOUT=20

SPECIAL_IP="192.168.21.53"
SRC_9_SOC1="192.168.9.2"
SRC_9_SOC2="192.168.9.3"
SRC_10_SOC1="192.168.10.2"
SRC_10_SOC2="192.168.10.3"
VIA_9="192.168.9.1"
VIA_10="192.168.10.1"

FAIL_LOG="/tmp/deploy-nas-fail.$$.log"
> "$FAIL_LOG"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

TMP_HELPER="/tmp/deploy-nas-helper.$$.sh"

###############################################################################
# 检查依赖
###############################################################################
check_deps() {
  if ! command -v sshpass &>/dev/null; then
    echo -e "${YELLOW}sshpass not found, installing...${NC}"
    sudo apt-get update -qq && sudo apt-get install -y -qq sshpass
  fi
}

###############################################################################
# 生成本地 helper 脚本 (会被 scp 到远程执行)
# 参数: $1=src_soc1 $2=src_soc2 $3=gateway
###############################################################################
gen_helper() {
  local src_soc1="$1"
  local src_soc2="$2"
  local gateway="$3"

  cat > "$TMP_HELPER" << HELPEREOF
#!/usr/bin/env bash
set -e
export LC_ALL=C

echo "  [1/6] Lazy-unmount hung /media/nas (if any)..."
umount -l /media/nas 2>/dev/null || true
echo "    Clean"

echo "  [2/6] Deploying systemd service..."
cat > /etc/systemd/system/add-nas-route.service << 'UNITEOF'
[Unit]
Description=Add persistent route to NAS (192.168.2.118)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh -c '\
  if ip -4 addr show mgbe3_0 | grep -q -E "172\\\\.168\\\\.16\\\\.101|192\\\\.168\\\\.1\\\\.100"; then \
    ip route replace 192.168.2.118/32 via ${gateway} dev mgbe3_0 src ${src_soc1}; \
    echo "NAS route added (soc1: via ${gateway} src ${src_soc1})"; \
  elif ip -4 addr show mgbe3_0 | grep -q -E "172\\\\.168\\\\.16\\\\.103|192\\\\.168\\\\.1\\\\.101"; then \
    ip route replace 192.168.2.118/32 via ${gateway} dev mgbe3_0 src ${src_soc2}; \
    echo "NAS route added (soc2: via ${gateway} src ${src_soc2})"; \
  else \
    echo "Unknown SoC, skipping route"; \
  fi'

[Install]
WantedBy=multi-user.target
UNITEOF
echo "    Service file written"

echo "  [3/6] Configuring /etc/fstab..."
if ! grep -q "192.168.2.118/ad-data" /etc/fstab 2>/dev/null; then
  echo "//192.168.2.118/ad-data /media/nas cifs username=wantl,password=Mm20000430,_netdev,file_mode=0755,dir_mode=0755 0 0" >> /etc/fstab
  echo "    fstab entry added"
else
  echo "    fstab entry already exists, skipping"
fi

echo "  [4/6] Starting systemd service..."
systemctl daemon-reload
systemctl enable add-nas-route.service 2>/dev/null || true
systemctl restart add-nas-route.service 2>/dev/null || true
sleep 1

echo "  [5/6] Creating /media/nas..."
mkdir -p /media/nas
chown -R nvidia:nvidia /media/nas
echo "    Done"

echo "  [6/6] Mounting NAS..."
mount -a 2>&1 || true

echo ""
echo "  --- Verification ---"
ip route show 192.168.2.118 2>/dev/null && echo "  [OK] Route exists" || echo "  [WARN] Route check failed"
mountpoint -q /media/nas 2>/dev/null && echo "  [OK] /media/nas mounted" || echo "  [WARN] Mount check failed"
echo ""
HELPEREOF
}

###############################################################################
# 部署到单个 SoC
###############################################################################
deploy_one() {
  local host="$1"
  local port="$2"
  local soc_label="$3"
  local src_soc1="$4"
  local src_soc2="$5"
  local gateway="$6"

  echo -e "${YELLOW}>>> [${host}:${port} ${soc_label}] via=${gateway} src=${src_soc1}/${src_soc2}${NC}"

  # 1. 生成本地 helper 脚本
  gen_helper "$src_soc1" "$src_soc2" "$gateway"

  # 2. scp 到远程
  if ! sshpass -p "$SSH_PASS" scp \
       -P "$port" \
       -o StrictHostKeyChecking=no \
       -o UserKnownHostsFile=/dev/null \
       -o ConnectTimeout=5 \
       -o LogLevel=ERROR \
       "$TMP_HELPER" \
       "${SSH_USER}@${host}:/tmp/deploy-nas-helper.sh" 2>/dev/null; then
    echo -e "${RED}    SCP failed${NC}"
    return 1
  fi

  # 3. ssh 执行: echo 密码 | sudo -S bash 脚本文件
  if ! echo "$SUDO_PASS" | timeout "$TIMEOUT" sshpass -p "$SSH_PASS" ssh \
       -p "$port" \
       -o StrictHostKeyChecking=no \
       -o UserKnownHostsFile=/dev/null \
       -o ConnectTimeout=5 \
       -o ServerAliveInterval=5 \
       -o ServerAliveCountMax=2 \
       -o LogLevel=ERROR \
       "${SSH_USER}@${host}" \
       "export LC_ALL=C; sudo -S bash /tmp/deploy-nas-helper.sh; rm -f /tmp/deploy-nas-helper.sh" 2>&1; then
    echo -e "${RED}    Execution failed${NC}"
    return 1
  fi

  return 0
}

###############################################################################
# 主流程
###############################################################################
main() {
  check_deps

  echo "============================================"
  echo "  NAS Route + Mount Deployment"
  echo "  Targets: 192.168.21.${BASE_IP_START}-${BASE_IP_END}"
  echo "  SoC: soc1 (port ${SOC1_PORT}) + soc2 (port ${SOC2_PORT})"
  echo "  Total: $(( (BASE_IP_END - BASE_IP_START + 1) * 2 )) targets"
  echo "  Special: 192.168.21.53 via ${VIA_9} src ${SRC_9_SOC1}/${SRC_9_SOC2}"
  echo "============================================"
  echo ""

  total=0

  for ip_suffix in $(seq "$BASE_IP_START" "$BASE_IP_END"); do
    ip="192.168.21.${ip_suffix}"

    if [ "$ip" = "$SPECIAL_IP" ]; then
      local src2="$SRC_9_SOC1"
      local src3="$SRC_9_SOC2"
      local via="$VIA_9"
    else
      local src2="$SRC_10_SOC1"
      local src3="$SRC_10_SOC2"
      local via="$VIA_10"
    fi

    # soc1
    total=$((total + 1))
    (
      if deploy_one "$ip" "$SOC1_PORT" "soc1" "$src2" "$src3" "$via"; then
        echo -e "${GREEN}<<< [${ip}:${SOC1_PORT} soc1] SUCCESS${NC}"
      else
        echo -e "${RED}<<< [${ip}:${SOC1_PORT} soc1] FAILED${NC}"
        echo "${ip}:${SOC1_PORT} soc1" >> "$FAIL_LOG"
      fi
    ) &

    # soc2
    total=$((total + 1))
    (
      if deploy_one "$ip" "$SOC2_PORT" "soc2" "$src2" "$src3" "$via"; then
        echo -e "${GREEN}<<< [${ip}:${SOC2_PORT} soc2] SUCCESS${NC}"
      else
        echo -e "${RED}<<< [${ip}:${SOC2_PORT} soc2] FAILED${NC}"
        echo "${ip}:${SOC2_PORT} soc2" >> "$FAIL_LOG"
      fi
    ) &

    sleep 0.3
  done

  wait

  # 清理临时 helper
  rm -f "$TMP_HELPER"

  echo ""
  echo "============================================"
  echo "  Deployment Complete"
  echo "============================================"

  local fail_count
  fail_count=$(wc -l < "$FAIL_LOG" 2>/dev/null || echo 0)
  local success_count=$((total - fail_count))

  echo -e "${GREEN}Success: ${success_count}/${total}${NC}"
  if [ "$fail_count" -gt 0 ]; then
    echo -e "${RED}Failed:  ${fail_count}/${total}${NC}"
    echo "Failed targets:"
    cat "$FAIL_LOG"
  fi

  rm -f "$FAIL_LOG"
}

main "$@"
