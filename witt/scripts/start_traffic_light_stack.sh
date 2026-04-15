#!/usr/bin/env bash
# ==============================================================================
# 脚本名称: start_traffic_light_stack.sh
# 适用环境: Ubuntu (Xorg/Wayland), CPU/NVIDIA GPU, Mdrive Container
# 功能描述: 启动红绿灯回灌相关模块，包括 Debug_Driver-Camera 和 Perception-TrafficLight
# ==============================================================================

set -Eeuo pipefail
readonly DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
readonly CAMERA_CONFIG_NAME="h26x_to_nv12.pb.txt"
readonly LOCAL_CAMERA_CONFIG_PATH="${DIR}/../config/${CAMERA_CONFIG_NAME}"
readonly CONTAINER_CAMERA_CONFIG_PATH="/mdrive/mdrive_conf/modules/perception_trafficlights/${CAMERA_CONFIG_NAME}"
readonly LOCAL_TRAFFIC_LIGHT_CONFIG_PATH="$MDRIVE_ROOT/mdrive_conf/modules/perception_trafficlights/perception_traffic_light.pb.txt"
source "$DIR/utils.sh"

trap 'failure ${BASH_SOURCE[0]} ${LINENO} "$BASH_COMMAND"' ERR

if [[ -f "$LOCAL_CAMERA_CONFIG_PATH" ]]; then
    docker cp "$LOCAL_CAMERA_CONFIG_PATH" "${CONTAINER}:${CONTAINER_CAMERA_CONFIG_PATH}"
fi

mkdir -p "$MDRIVE_ROOT/data/test"

sed -i \
    's/^[[:space:]]*save_debug_img:[[:space:]]*false/  save_debug_img: true/g' \
    "$LOCAL_TRAFFIC_LIGHT_CONFIG_PATH"

log_info "正在启动红绿灯回灌模块: Perception-LiDAR & Debug_Driver-Camera & Perception-TrafficLight..."
docker exec -d "$CONTAINER" bash -c "
    sudo supervisorctl start Perception-LiDAR && \
    sudo supervisorctl start Debug_Driver-Camera && \
    sudo supervisorctl start Perception-TrafficLight
"
