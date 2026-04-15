#!/usr/bin/env bash
# ==============================================================================
# 脚本名称: start_replay_stack.sh
# 适用环境: Ubuntu (Xorg/Wayland), CPU/NVIDIA GPU, Mdrive Container
# 功能描述: 启动标准回播工具链，包括 Dreamview、Debug_Driver-LiDAR 和 Multiviz
# ==============================================================================

set -Eeuo pipefail
readonly DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
readonly MULTIVIZ_CONFIG_NAME="customized_20260403.multiviz.yaml"
readonly LOCAL_MULTIVIZ_CONFIG_PATH="${DIR}/../config/${MULTIVIZ_CONFIG_NAME}"
readonly CONTAINER_MULTIVIZ_CONFIG_PATH="/mdrive/${MULTIVIZ_CONFIG_NAME}"
source "$DIR/utils.sh"

trap 'failure ${BASH_SOURCE[0]} ${LINENO} "$BASH_COMMAND"' ERR

xhost +local:docker >/dev/null 2>&1 || true

if [[ -f "$LOCAL_MULTIVIZ_CONFIG_PATH" ]]; then
    docker cp "$LOCAL_MULTIVIZ_CONFIG_PATH" "${CONTAINER}:${CONTAINER_MULTIVIZ_CONFIG_PATH}"
fi

log_info "正在启动标准回播模块: Dreamview & Debug_Driver-LiDAR..."
docker exec -d "$CONTAINER" bash -c "
    sudo -E bash /mdrive/mdrive/scripts/cmd.sh && \
    sudo supervisorctl start Dreamview && \
    sudo supervisorctl start Debug_Driver-LiDAR
"

log_info "正在启动 mdrive_multiviz..."
if docker exec "$CONTAINER" ls /tmp/.Xauthority >/dev/null 2>&1; then
    docker exec -d \
        -e DISPLAY="${DISPLAY:-:0}" \
        -e XAUTHORITY="/tmp/.Xauthority" \
        "$CONTAINER" \
        /mdrive/mdrive/bin/mdrive_multiviz -d "$CONTAINER_MULTIVIZ_CONFIG_PATH"
else
    docker exec -d \
        "$CONTAINER" \
        /mdrive/mdrive/bin/mdrive_multiviz -d "$CONTAINER_MULTIVIZ_CONFIG_PATH"
fi

nohup xdg-open "http://localhost:8888" >/dev/null 2>&1 &
