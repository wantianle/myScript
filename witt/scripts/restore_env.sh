#!/bin/bash

set -Eeuo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/utils.sh"
trap 'failure ${BASH_SOURCE[0]} ${LINENO} "$BASH_COMMAND"' ERR
VMC_SH="$MDRIVE_ROOT/vmc.sh"
find_version() {
    content=""
    local input_data="${VERSION}"
    if [ ! -f "$input_data" ]; then
        log_error "文件不存在: $input_data"
        exit 1
    fi
    if [[ "$input_data" =~ .*\.txt$ ]]; then
        log_info "使用指定的 version.txt 文件: $input_data"
        mdrive_ver=$(awk '$1=="mdrive" {print $2}' "$input_data")
        conf_ver=$(awk '$1=="mdrive_conf" {print $2}' "$input_data")
        model_ver=$(awk '$1=="mdrive_model" {print $2}' "$input_data")
        map_ver=$(awk '$1=="mdrive_map" {print $2}' "$input_data")
    else
        log_info "使用指定的 version.json 文件: $input_data"
        content=$(cat "$input_data")
        mdrive_ver=$(echo "$content" | jq -r .mdrive)
        conf_ver=$(echo "$content" | jq -r .mdrive_conf)
        model_ver=$(echo "$content" | jq -r .mdrive_model)
        map_ver=$(echo "$content" | jq -r .mdrive_map)
    fi
    vehicle_model_code=$(echo "$conf_ver" | cut -d'.' -f1)
    echo "------------------------------------------"
    echo "解析得到的版本信息:"
    echo "mdrive:             $mdrive_ver"
    echo "mdrive_conf:        $conf_ver"
    echo "mdrive_model:       $model_ver"
    echo "mdrive_map:         $map_ver"
    echo "vehicle_model_code: $vehicle_model_code"
    echo "------------------------------------------"
    if [ -z "$mdrive_ver" ] || [ -z "$conf_ver" ]; then
        log_error "未能从文件中解析出 mdrive 或 mdrive_conf 版本"
        exit 1
    fi
}

show_info() {
    if [ -z "${2:-}" ]; then
        return 0
    fi
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

show_git_info() {
    log_info "Git 详细版本信息"
    show_info mdrive $mdrive_ver
    show_info mdrive_conf $conf_ver
    show_info mdrive_map $map_ver
    show_info mdrive_model $model_ver
}

sync_local_env() {
    log_info "同步本地环境..."
    local cur_vehicle_model=$(grep '^MDRIVE_VEHICLE_MODEL=' "$VMC_SH" | cut -d '"' -f2)
    local cur_vehicle=$(grep '^MDRIVE_VEHICLE_NAME=' "$VMC_SH" | cut -d '"' -f2)
    local cur_mdrive_ver=$(grep '^MDRIVE_VERSION=' "$VMC_SH" | cut -d '=' -f2)
    local cur_conf_ver=$(grep '^MDRIVE_CONF_VERSION=' "$VMC_SH" | cut -d '=' -f2)
    local cur_model_ver=$(grep '^MDRIVE_MODEL_VERSION=' "$VMC_SH" | cut -d '=' -f2)
    local cur_map_ver=$(grep '^MDRIVE_MAP_VERSION=' "$VMC_SH" | cut -d '=' -f2)
    if [ "$cur_vehicle_model" = "$vehicle_model_code" ] &&
       [ "$cur_vehicle" = "$VEHICLE" ] &&
       [ "$cur_mdrive_ver" = "$mdrive_ver" ] &&
       [ "$cur_conf_ver" = "$conf_ver" ] &&
       [ "$cur_model_ver" = "$model_ver" ] &&
       [ "$cur_map_ver" = "$map_ver" ]; then
        return
    fi
    sed -i -e "/^MDRIVE_VEHICLE_MODEL/c\MDRIVE_VEHICLE_MODEL=\"$vehicle_model_code\"" \
        -e "/^MDRIVE_VEHICLE_NAME/c\MDRIVE_VEHICLE_NAME=\"$VEHICLE\"" \
        -e "/^MDRIVE_VERSION/c\MDRIVE_VERSION=$mdrive_ver" \
        -e "/^MDRIVE_CONF_VERSION/c\MDRIVE_CONF_VERSION=$conf_ver" \
        -e "/^MDRIVE_MODEL_VERSION/c\MDRIVE_MODEL_VERSION=$model_ver" \
        -e "/^MDRIVE_MAP_VERSION/c\MDRIVE_MAP_VERSION=$map_ver" "$VMC_SH"
    source "$VMC_SH"
}

start_docker() {
    if [ -z "$(docker ps -q -f "name=^/${CONTAINER}$")" ]; then
        log_warnning "容器 [${CONTAINER}] 不存在或未运行，尝试启动..."
        START_SCRIPT="${MDRIVE_ROOT}/mdrive/docker/dev_start.sh"
        if [ ! -f "$START_SCRIPT" ]; then
            source "$VMC_SH"
        fi
        bash "$START_SCRIPT" --remove
    fi
    docker exec -d "$CONTAINER" bash -c 'sudo -E bash /mdrive/mdrive/scripts/cmd.sh && sudo supervisorctl start Dreamview && sudo supervisorctl start Debug_Driver-LiDAR'
    log_info "Supervisor 和 Dreamview 已启动..."
}

# ================= 主流程 =================
find_version
# show_git_info
sync_local_env
start_docker
