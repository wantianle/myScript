#!/usr/bin/env bash
# ==============================================================================
# 脚本名称: start.sh
# 适用环境: Ubuntu (Xorg/Wayland), CPU/NVIDIA GPU, Mdrive Container
# 功能描述: 启动 Supervisor 管理工具、Mdrive 可视化工具、Multiviz 和相关服务
# ==============================================================================

set -Eeuo pipefail
readonly DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
readonly VIZ_CONFIG="customized_20260403.multiviz.yaml"
local_cfg_path="${DIR}/../config/${VIZ_CONFIG}"
docker_cfg_path="/mdrive/${VIZ_CONFIG}"
source "$DIR/utils.sh"

trap 'failure ${BASH_SOURCE[0]} ${LINENO} "$BASH_COMMAND"' ERR

# 环境检查与授权
# 允许 Docker 访问 X Server (解决常见的 Connection Refused)
xhost +local:docker >/dev/null 2>&1 || true

# 准备配置文件
if [[ -f "$local_cfg_path" ]]; then
    docker cp "$local_cfg_path" "${CONTAINER}:${docker_cfg_path}"
fi

# 启动后台服务 Supervisor
log_info "正在启动 Supervisor 模块: Dreamview & Debug_Driver-LiDAR..."
docker exec -d "$CONTAINER" bash -c "
    sudo -E bash /mdrive/mdrive/scripts/cmd.sh && \
    sudo supervisorctl start Dreamview && \
    sudo supervisorctl start Debug_Driver-LiDAR
"

# 启动可视化工具 Multiviz
log_info "正在启动 mdrive_multiviz..."
# 检查容器内是否存在授权文件
if docker exec "$CONTAINER" ls /tmp/.Xauthority >/dev/null 2>&1; then
    docker exec -d \
    -e DISPLAY="${DISPLAY:-:0}" \
    -e XAUTHORITY="/tmp/.Xauthority" \
    "$CONTAINER" \
    /mdrive/mdrive/bin/mdrive_multiviz -d "$docker_cfg_path"
else
    docker exec -d "$CONTAINER" /mdrive/mdrive/bin/mdrive_multiviz -d "$docker_cfg_path"
fi


# 打开 Web 界面
nohup xdg-open "http://localhost:8888" >/dev/null 2>&1 &
