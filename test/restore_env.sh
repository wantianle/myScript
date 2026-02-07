#!/bin/bash

# ================= 默认配置 =================
set -Eeuo pipefail
LOG_SHOW_TIME=0
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/utils/logger.sh"
# NAS 挂载根目录
NAS_ROOT="/media/nas/04.mdrive3/01.road_test"
# 本地需要修改的环境配置文件路径
VMC_SH="$HOME/project/vmc.sh"
# Docker 容器名称
CONTAINER_NAME="mdrive_dev_vmc_minieye"
# docker 容器挂载路径 (用于进入容器的脚本路径)
VMC_SOFTWARE="$HOME/project"
# ===========================================
usage() {
    cat <<EOF
Usage: $0 [options] ...
这个脚本用于根据路测时间戳，自动查找NAS上的版本信息，并同步到本地Docker环境。

OPTIONS:
    -t, --timestamp     数据时间戳 (必填，除非指定了 -p), 格式: YYYYMMDD-HHMM (例如: 20251103-1206)
    -v, --vehicle       车辆ID (可选), 例如：XZT500020
    -p, --path          直接指定 version.json 的路径 (如果指定此项，则忽略 -t)，例如: ./version.json
    -h, --help          显示帮助信息

Examples:
    1. nas 自动查找 version.json 并同步环境:
    $0 -t 20251103-1206 -v XZT500020
    2. 直接指定 version.json 路径:
    $0 -v XZT500020 -p /media/data/20250926/bag/20250926-191101_soc1/version.json

EOF
}

# 参数解析
VEHICLE_ID=""
TIME_STAMP=""
MANUAL_PATH=""

while [ $# -gt 0 ]; do
    case "$1" in
        -t|--timestamp) TIME_STAMP="$2"; shift 2 ;;
        -v|--vehicle) VEHICLE_ID="$2"; shift 2 ;;
        -p|--path) MANUAL_PATH="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) log_error "未知参数: $1"; usage; exit 1 ;;
    esac
done

# 检查环境依赖
if [ ! -d "$NAS_ROOT" ] && [ -z $MANUAL_PATH ] ; then
    log_error "NAS 目录不存在: $NAS_ROOT"
    echo "请先挂载 NAS: sudo mount -t cifs //hfs.minieye.tech/ad-data /media/nas -o username=工号,password=密码,uid=$(id -u)"
    exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
    log_info "jq 未安装，尝试安装..."
    sudo apt update && sudo apt install -y jq
fi

if [ ! -f "$VMC_SH" ]; then
    log_error "本地配置文件未找到: $VMC_SH"
    echo "请修改脚本头部的 VMC_SH 变量指向正确的文件。"
    exit 1
fi

# ================= 1: 寻找 version.json =================
find_MANUAL_PATH() {
    if [ -n "$MANUAL_PATH" ]; then
        if [ -f "$MANUAL_PATH" ]; then
            log_ok "使用指定的 version.json 路径: $MANUAL_PATH"
            return 0
        else
            log_error "指定的 version.json 文件不存在: $MANUAL_PATH"
            exit 1
        fi
    fi

    if [ -z "$TIME_STAMP" ]; then
        log_error "必须提供时间戳 (-t) 或 version.json 直接路径 (-p)"
        usage
        exit 1
    fi

    local yyyy=${TIME_STAMP:0:4}
    local yyyymmdd=${TIME_STAMP:0:8}
    local HHMM=${TIME_STAMP:9:4}
    local search_dir="$NAS_ROOT/$VEHICLE_ID/$yyyy"

    # 兼容 soc1 后缀目录
    local day_dir_soc1=$(ls -d "${search_dir}/${yyyymmdd}"*_soc1 2>/dev/null | head -n 1)
    local day_dir_normal="${search_dir}/${yyyymmdd}"
    local target_day_dir=""

    if [ -d "$day_dir_soc1" ]; then
        target_day_dir="$day_dir_soc1"
    elif [ -d "$day_dir_normal" ]; then
        target_day_dir="$day_dir_normal"
    else
        log_error "未找到日期目录: $search_dir 下没有 ${yyyymmdd} 或 ${yyyymmdd}_soc1"
        exit 1
    fi

    # 寻找 bag 目录
    local bag_root_dir=""
    if [ -d "$target_day_dir/bag" ]; then
        bag_root_dir="$target_day_dir/bag"
    elif [ -d "$target_day_dir/*/bag" ]; then
        # 处理可能的中间层级
        bag_root_dir=$(ls -d $target_day_dir/*/bag | head -n 1)
    fi

    if [ -z "$bag_root_dir" ]; then
        log_error "在 $target_day_dir 下未找到 bag 目录"
        exit 1
    fi

    # 精确查找 soc1 且包含时间点的 record 文件
    log_info "正在搜索 $bag_root_dir ..."
    # 查找文件名包含 HHMM 的 .record 文件
    local record_file=$(find "$bag_root_dir" -type f -path "*soc1*" -name "*.record.*${HHMM}*" | head -n 1)

    if [ -z "$record_file" ]; then
        log_error "未找到时间点 $HHMM 附近的 Record 文件"
        exit 1
    fi

    local record_dir=$(dirname "$record_file")
    MANUAL_PATH="$record_dir/version.json"

    if [ ! -f "$MANUAL_PATH" ]; then
        log_error "找到录制目录，但缺少 version.json: $MANUAL_PATH"
        exit 1
    fi

    log_info "定位成功: $MANUAL_PATH"
    log_info "对应 Record: $record_file"
}

# ================= 2: 解析显示 Git 版本 =================
mdrive_ver=$(jq -r .mdrive "$MANUAL_PATH")
conf_ver=$(jq -r .mdrive_conf "$MANUAL_PATH")
# dep_ver=$(jq -r .mdrive_dep "$MANUAL_PATH")
model_ver=$(jq -r .mdrive_model "$MANUAL_PATH")
map_ver=$(jq -r .mdrive_map "$MANUAL_PATH")
vehicle_model_code=$(echo "$conf_ver" | cut -d'.' -f1)

show_git_info() {
    log_step "===== 1. 解析版本信息 ====="
    show_info() {
        vmc search --name "$1" --version "$2" --verbose 2>/dev/null \
        | awk '
            function print_block() {
                if (buffer != "") {
                    if (!has_platform || is_amd64) {
                        print "--------------------"
                        printf "%s", buffer
                    }
                }
            }
            /^ *Name:/ {
                print_block()
                buffer = ""
                has_platform = 0
                is_amd64 = 0
            }
            /^ *Name:/ || /^ *Version:/ || /^ *Platform:/ || /^ *ReleaseTime:/ || /^ *GitBranch:/ {
                buffer = buffer $0 "\n"
                if ($1 ~ /^Platform:/) {
                    has_platform = 1
                    if ($2 == "amd64" || $2 == "any") {
                        is_amd64 = 1
                    }
                }
            }
            END {
                print_block()
            }
        '
    }

    jq . "$MANUAL_PATH"

    # 使用 vmc 反查 Git 信息
    if command -v vmc >/dev/null 2>&1; then
        log_ok "Git 详细版本信息"
        show_info mdrive $mdrive_ver
        show_info mdrive_conf $conf_ver
        # show_info mdrive_dep $dep_ver
        show_info mdrive_map $map_ver
        show_info mdrive_model $model_ver
    else
        log_info "本地未安装 'vmc' 工具!"
    fi
}

# ================= 3: 同步本地环境配置文件 =================
sync_local_env() {
    log_step "===== 2. 同步本地环境 ($VMC_SH) ====="

    local cur_vehicle_model=$(grep '^MDRIVE_VEHICLE_MODEL=' "$VMC_SH" | cut -d '"' -f2)
    local cur_vehicle_id=$(grep '^MDRIVE_VEHICLE_ID=' "$VMC_SH" | cut -d '"' -f2)
    local cur_mdrive_ver=$(grep '^MDRIVE_VERSION=' "$VMC_SH" | cut -d '=' -f2)
    local cur_conf_ver=$(grep '^MDRIVE_CONF_VERSION=' "$VMC_SH" | cut -d '=' -f2)
    local cur_model_ver=$(grep '^MDRIVE_MODEL_VERSION=' "$VMC_SH" | cut -d '=' -f2)
    local cur_map_ver=$(grep '^MDRIVE_MAP_VERSION=' "$VMC_SH" | cut -d '=' -f2)

    # 判断是否全部一致
    if [ "$cur_vehicle_model" = "$vehicle_model_code" ] &&
       [ "$cur_vehicle_id" = "$VEHICLE_ID" ] &&
       [ "$cur_mdrive_ver" = "$mdrive_ver" ] &&
       [ "$cur_conf_ver" = "$conf_ver" ] &&
       [ "$cur_model_ver" = "$model_ver" ] &&
       [ "$cur_map_ver" = "$map_ver" ]; then
        log_ok "vmc.sh 已是最新状态，无需更新"
        return
    fi

    # 只有不相等时才更新
    sed -i -e "/^MDRIVE_VEHICLE_MODEL/c\MDRIVE_VEHICLE_MODEL=\"$vehicle_model_code\"" \
        -e "/^MDRIVE_VEHICLE_ID/c\MDRIVE_VEHICLE_ID=\"$VEHICLE_ID\"" \
        -e "/^MDRIVE_VERSION/c\MDRIVE_VERSION=$mdrive_ver" \
        -e "/^MDRIVE_CONF_VERSION/c\MDRIVE_CONF_VERSION=$conf_ver" \
        -e "/^MDRIVE_MODEL_VERSION/c\MDRIVE_MODEL_VERSION=$model_ver" \
        -e "/^MDRIVE_MAP_VERSION/c\MDRIVE_MAP_VERSION=$map_ver" "$VMC_SH"

    source "$VMC_SH"
    log_ok "vmc.sh 已更新"
}


# ================= 4: 进 Docker =================
enter_docker() {

    # 判断容器是否正在运行
    if [ -n "$(docker ps -q -f "name=^/${CONTAINER_NAME}$")" ]; then
        log_warnning "容器 [${CONTAINER_NAME}] 已存在且正在运行，跳过启动"
    else
        log_warnning "容器 [${CONTAINER_NAME}] 不存在或未运行，准备启动"

        START_SCRIPT="${VMC_SOFTWARE}/mdrive/docker/dev_start.sh"

        if [ ! -f "$START_SCRIPT" ]; then
            log_warnning "启动脚本不存在: $START_SCRIPT, 尝试重新配置环境..."

            source "$VMC_SH"

            if [ ! -f "$START_SCRIPT" ]; then
                log_error "重新配置后仍未找到启动脚本"
                return 1
            fi
        fi
        bash "$START_SCRIPT" --remove
    fi


    docker exec -it "$CONTAINER_NAME" bash -c 'sudo -E bash /mdrive/mdrive/scripts/cmd.sh && sudo supervisorctl start Dreamview'
    log_ok "Supervisor status 和 Dreamview 已启动..."

    docker exec -d "$CONTAINER_NAME" bash -c "/mdrive/mdrive/bin/mdrive_multiviz >/dev/null 2>&1"

    log_ok "mdrive_multiviz 已启动..."

    # 打开浏览器
    nohup xdg-open http://localhost:9001 >/dev/null 2>&1 &
    sleep 1
    nohup xdg-open http://localhost:8888 >/dev/null 2>&1 &

    log_ok "进入 Docker 容器: ${CONTAINER_NAME}"
    bash ${VMC_SOFTWARE}/mdrive/docker/dev_into.sh
}

# ================= 主流程 =================
find_MANUAL_PATH
show_git_info
sync_local_env
enter_docker
