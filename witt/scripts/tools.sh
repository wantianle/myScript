#!/bin/bash
set -Eeuo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/utils.sh"
trap 'failure ${BASH_SOURCE[0]} ${LINENO} "$BASH_COMMAND"' ERR

docker exec -d "$CONTAINER" bash -c 'sudo -E bash /mdrive/mdrive/scripts/cmd.sh && sudo supervisorctl start Dreamview && sudo supervisorctl start Debug_Driver-LiDAR'
log_info "Supervisor: Debug_Driver-LiDAR 和 Dreamview 已启动..."

cp -n "${BASH_SOURCE[0]%/*}/../config/customized_20260403.multiviz.yaml" "$MDRIVE_ROOT/"
docker exec -d "$CONTAINER" bash -c "/mdrive/mdrive/bin/mdrive_multiviz -d /mdrive/customized_20260403.multiviz.yaml >/dev/null 2>&1"
log_info "mdrive_multiviz 已启动..."

nohup xdg-open http://localhost:8888 >/dev/null 2>&1 &
