#!/bin/bash

set -Eeuo pipefail
LOG_SHOW_TIME=0
UTILS_DIR="${BASH_SOURCE[0]%/*}/../utils"
source "$UTILS_DIR/logger.sh"

while getopts "v:t:p:" opt; do
    case $opt in
        v) vehicle="$OPTARG" ;;
        t) target_date="$OPTARG" ;;
        p) version="$OPTARG" ;;
        *) exit 0 ;;
    esac
done

if ! command -v jq >/dev/null 2>&1; then
    log_info "jq 未安装，尝试安装..."
    sudo apt-get update && sudo apt-get install -y jq
fi

if ! command -v vmc >/dev/null 2>&1; then
    log_info "本地未安装 'vmc' 工具，现在尝试安装..."
    bash "${BASH_SOURCE[0]%/*}/vmc_deploy.sh"
    source ~/.bashrc
fi

if [ ! -f "$VMC_SH" ]; then
    log_error "配置文件未找到: $VMC_SH, 现在尝试创建..."
    mkdir -p "$MDRIVE_ROOT"
    cp "$UTILS_DIR/vmc.sh_for_tester" "$MDRIVE_ROOT/vmc.sh"
    chmod +x "$MDRIVE_ROOT/vmc.sh"
fi

find_version() {
    json_content=""
    local input_data="$version"
    if [[ "$input_data" =~ ^\{.*\}$ ]]; then
        log_info "使用指定的 JSON 数据..."
        json_content="$input_data"
    else
        log_info "使用指定的 version.json 文件: $input_data"
        json_content=$(cat "$input_data/version.json")
    fi
    if [ -n "$json_content" ]; then
        mdrive_ver=$(echo "$json_content" | jq -r .mdrive)
        conf_ver=$(echo "$json_content" | jq -r .mdrive_conf)
        model_ver=$(echo "$json_content" | jq -r .mdrive_model)
        map_ver=$(echo "$json_content" | jq -r .mdrive_map)
        vehicle_model_code=$(echo "$conf_ver" | cut -d'.' -f1)
    else
        log_error "未能获取有效的 JSON 内容"
        exit 1
    fi
}

show_git_info() {
    log_info "===== 1. 解析版本信息 ====="
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
    echo "$json_content" | jq .
    log_info "Git 详细版本信息"
    show_info mdrive $mdrive_ver
    show_info mdrive_conf $conf_ver
    show_info mdrive_map $map_ver
    show_info mdrive_model $model_ver
}

sync_local_env() {
    log_info "===== 2. 同步本地环境 ($VMC_SH) ====="
    local cur_vehicle_model=$(grep '^MDRIVE_VEHICLE_MODEL=' "$VMC_SH" | cut -d '"' -f2)
    local cur_vehicle=$(grep '^MDRIVE_VEHICLE_NAME=' "$VMC_SH" | cut -d '"' -f2)
    local cur_mdrive_ver=$(grep '^MDRIVE_VERSION=' "$VMC_SH" | cut -d '=' -f2)
    local cur_conf_ver=$(grep '^MDRIVE_CONF_VERSION=' "$VMC_SH" | cut -d '=' -f2)
    local cur_model_ver=$(grep '^MDRIVE_MODEL_VERSION=' "$VMC_SH" | cut -d '=' -f2)
    local cur_map_ver=$(grep '^MDRIVE_MAP_VERSION=' "$VMC_SH" | cut -d '=' -f2)
    if [ "$cur_vehicle_model" = "$vehicle_model_code" ] &&
       [ "$cur_vehicle" = "$vehicle" ] &&
       [ "$cur_mdrive_ver" = "$mdrive_ver" ] &&
       [ "$cur_conf_ver" = "$conf_ver" ] &&
       [ "$cur_model_ver" = "$model_ver" ] &&
       [ "$cur_map_ver" = "$map_ver" ]; then
        log_info "vmc.sh 已是最新状态，无需更新"
        return
    fi
    sed -i -e "/^MDRIVE_VEHICLE_MODEL/c\MDRIVE_VEHICLE_MODEL=\"$vehicle_model_code\"" \
        -e "/^MDRIVE_VEHICLE_NAME/c\MDRIVE_VEHICLE_NAME=\"$vehicle\"" \
        -e "/^MDRIVE_VERSION/c\MDRIVE_VERSION=$mdrive_ver" \
        -e "/^MDRIVE_CONF_VERSION/c\MDRIVE_CONF_VERSION=$conf_ver" \
        -e "/^MDRIVE_MODEL_VERSION/c\MDRIVE_MODEL_VERSION=$model_ver" \
        -e "/^MDRIVE_MAP_VERSION/c\MDRIVE_MAP_VERSION=$map_ver" "$VMC_SH"
    source "$VMC_SH"
    log_info "vmc.sh 已更新"
}

enter_docker() {

    if [ -n "$(docker ps -q -f "name=^/${CONTAINER}$")" ]; then
        log_info "容器 [${CONTAINER}] 已存在且正在运行，跳过启动..."
    else
        log_warn "容器 [${CONTAINER}] 不存在或未运行，尝试启动..."
        START_SCRIPT="${MDRIVE_ROOT}/mdrive/docker/dev_start.sh"
        if [ ! -f "$START_SCRIPT" ]; then
            log_warn "启动脚本不存在: $START_SCRIPT, 请检查${MDRIVE_ROOT}是否有 mdrive, 尝试重新配置环境..."
            source "$VMC_SH"
        fi
        bash "$START_SCRIPT" --remove
    fi


    docker exec -d "$CONTAINER" bash -c 'sudo -E bash /mdrive/mdrive/scripts/cmd.sh && sudo supervisorctl start Dreamview'
    log_info "Supervisor status 和 Dreamview 已启动..."

    docker exec -d "$CONTAINER" bash -c "/mdrive/mdrive/bin/mdrive_multiviz >/dev/null 2>&1"

    log_info "mdrive_multiviz 已启动..."

    # 打开浏览器
    nohup xdg-open http://localhost:9001 >/dev/null 2>&1 &
    sleep 1
    nohup xdg-open http://localhost:8888 >/dev/null 2>&1 &

    log_info "进入 Docker 容器: ${CONTAINER}"
    bash ${MDRIVE_ROOT}/mdrive/docker/dev_into.sh
}

# ================= 主流程 =================
find_version
show_git_info
sync_local_env
enter_docker
