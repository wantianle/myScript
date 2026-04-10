#!/usr/bin/env bash
# ==============================================================================
# 脚本名称: start.sh
# 适用环境: Ubuntu (Xorg/Wayland), CPU/NVIDIA GPU, Mdrive Container
# 功能描述: 启动 Supervisor 管理工具、Mdrive 可视化工具、Multiviz 和相关服务
# ==============================================================================

set -Eeuo pipefail
readonly DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
readonly CAMERA_CONFIG="h26x_to_nv12.pb.txt"
local_camera_cfg_path="${DIR}/../config/${CAMERA_CONFIG}"
docker_camera_cfg_path="/mdrive/mdrive_conf/modules/perception_trafficlights/${CAMERA_CONFIG}"
local_traffic_cfg_path="$MDRIVE_ROOT/mdrive_conf/modules/perception_trafficlights/perception_traffic_light.pb.txt"
source "$DIR/utils.sh"

trap 'failure ${BASH_SOURCE[0]} ${LINENO} "$BASH_COMMAND"' ERR

# 准备配置文件
if [[ -f "$local_camera_cfg_path" ]]; then
    docker cp "$local_camera_cfg_path" "${CONTAINER}:${docker_camera_cfg_path}"
fi

mkdir -p $MDRIVE_ROOT/data/test

sed -i 's/^[[:space:]]*save_debug_img:[[:space:]]*false/  save_debug_img: true/g' $local_traffic_cfg_path

# 启动后台服务 Supervisor
log_info "正在启动 Supervisor 模块: Debug_Driver-LiDAR & Debug_Driver-Camera & Perception-TrafficLight..."
docker exec -d "$CONTAINER" bash -c "
    sudo supervisorctl start Perception-LiDAR && \
    sudo supervisorctl start Debug_Driver-Camera && \
    sudo supervisorctl start Perception-TrafficLight
"
