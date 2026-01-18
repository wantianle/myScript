set -Eeuo pipefail
source "${BASH_SOURCE[0]%/*}/utils.sh"
trap 'failure ${BASH_SOURCE[0]} ${LINENO} "$BASH_COMMAND"' ERR

cp -n "${BASH_SOURCE[0]%/*}/../docs/customized_20260115.multiviz.yaml" "$MDRIVE_ROOT/"
docker exec -d "$CONTAINER" bash -c "/mdrive/mdrive/bin/mdrive_multiviz -d /mdrive/customized_20260115.multiviz.yaml >/dev/null 2>&1"
log_info "mdrive_multiviz 已启动..."
# 打开浏览器
nohup xdg-open http://localhost:9001 >/dev/null 2>&1 &
sleep 1
nohup xdg-open http://localhost:8888 >/dev/null 2>&1 &
