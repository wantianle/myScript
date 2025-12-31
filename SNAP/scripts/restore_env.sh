#!/bin/bash

# ================= 默认配置 =================
set -Eeuo pipefail
LOG_SHOW_TIME=0
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../utils/logger.sh"

nas_root="$NAS_ROOT"
vmc_sh="$VMC_SH"
container="$CONTAINER"
mdrive_root="$MDRIVE_ROOT"
# ===========================================
# 参数解析
# vehicle=""
# targer_date=""
# version_path=""

while [ $# -gt 0 ]; do
    case "$1" in
        -t|--target_date) targer_date="$2"; shift 2 ;;
        -v|--vehicle) vehicle="$2"; shift 2 ;;
        -p|--path) version_path="$2"; shift 2 ;;
        *) log_error "未知参数: $1"; usage; exit 1 ;;
    esac
done

# 检查环境依赖
if [ ! -d "$nas_root" ] && [ -z $version_path ] ; then
    log_error "NAS 目录不存在: $nas_root"
    echo "请先挂载 NAS: sudo mount -t cifs //hfs.minieye.tech/ad-data /media/nas -o username=工号,password=密码,uid=$(id -u)"
    exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
    log_info "jq 未安装，尝试安装..."
    sudo apt update && sudo apt install -y jq
fi

if [ ! -f "$vmc_sh" ]; then
    log_error "本地配置文件未找到: $vmc_sh"
    echo "请修改脚本头部的 vmc_sh 变量指向正确的文件。"
    exit 1
fi

# ================= 1: 寻找 version.json =================
find_version_path() {
    if [ -n "$version_path" ]; then
        if [ -f "$version_path" ]; then
            log_info "使用指定的 version.json 路径: $version_path"
            return 0
        else
            log_error "指定的 version.json 文件不存在: $version_path"
            exit 1
        fi
    fi

    if [ -z "$targer_date" ]; then
        log_error "必须提供时间戳 (-t) 或 version.json 直接路径 (-p)"
        usage
        exit 1
    fi

    local yyyy=${targer_date:0:4}
    local yyyymmdd=${targer_date:0:8}
    local HHMM=${targer_date:9:4}
    local search_dir="$nas_root/$vehicle/$yyyy"

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
    version_path="$record_dir/version.json"

    if [ ! -f "$version_path" ]; then
        log_error "找到录制目录，但缺少 version.json: $version_path"
        exit 1
    fi

    log_info "定位成功: $version_path"
    log_info "对应 Record: $record_file"
}

# ================= 2: 解析显示 Git 版本 =================
mdrive_ver=$(jq -r .mdrive "$version_path")
conf_ver=$(jq -r .mdrive_conf "$version_path")
# dep_ver=$(jq -r .mdrive_dep "$version_path")
model_ver=$(jq -r .mdrive_model "$version_path")
map_ver=$(jq -r .mdrive_map "$version_path")
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

    jq . "$version_path"

    # 使用 vmc 反查 Git 信息
    if command -v vmc >/dev/null 2>&1; then
        log_info "Git 详细版本信息"
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
    log_step "===== 2. 同步本地环境 ($vmc_sh) ====="

    local cur_vehicle_model=$(grep '^MDRIVE_vehicle_MODEL=' "$vmc_sh" | cut -d '"' -f2)
    local cur_vehicle=$(grep '^MDRIVE_vehicle=' "$vmc_sh" | cut -d '"' -f2)
    local cur_mdrive_ver=$(grep '^MDRIVE_VERSION=' "$vmc_sh" | cut -d '=' -f2)
    local cur_conf_ver=$(grep '^MDRIVE_CONF_VERSION=' "$vmc_sh" | cut -d '=' -f2)
    local cur_model_ver=$(grep '^MDRIVE_MODEL_VERSION=' "$vmc_sh" | cut -d '=' -f2)
    local cur_map_ver=$(grep '^MDRIVE_MAP_VERSION=' "$vmc_sh" | cut -d '=' -f2)

    # 判断是否全部一致
    if [ "$cur_vehicle_model" = "$vehicle_model_code" ] &&
       [ "$cur_vehicle" = "$vehicle" ] &&
       [ "$cur_mdrive_ver" = "$mdrive_ver" ] &&
       [ "$cur_conf_ver" = "$conf_ver" ] &&
       [ "$cur_model_ver" = "$model_ver" ] &&
       [ "$cur_map_ver" = "$map_ver" ]; then
        log_info "vmc.sh 已是最新状态，无需更新"
        return
    fi

    # 只有不相等时才更新
    sed -i -e "/^MDRIVE_vehicle_MODEL/c\MDRIVE_vehicle_MODEL=\"$vehicle_model_code\"" \
        -e "/^MDRIVE_vehicle/c\MDRIVE_vehicle=\"$vehicle\"" \
        -e "/^MDRIVE_VERSION/c\MDRIVE_VERSION=$mdrive_ver" \
        -e "/^MDRIVE_CONF_VERSION/c\MDRIVE_CONF_VERSION=$conf_ver" \
        -e "/^MDRIVE_MODEL_VERSION/c\MDRIVE_MODEL_VERSION=$model_ver" \
        -e "/^MDRIVE_MAP_VERSION/c\MDRIVE_MAP_VERSION=$map_ver" "$vmc_sh"

    source "$vmc_sh"
    log_info "vmc.sh 已更新"
}


# ================= 4: 进 Docker =================
enter_docker() {

    # 判断容器是否正在运行
    if [ -n "$(docker ps -q -f "name=^/${container}$")" ]; then
        log_warn "容器 [${container}] 已存在且正在运行，跳过启动"
    else
        log_warn "容器 [${container}] 不存在或未运行，准备启动"

        START_SCRIPT="${mdrive_root}/mdrive/docker/dev_start.sh"

        if [ ! -f "$START_SCRIPT" ]; then
            log_warn "启动脚本不存在: $START_SCRIPT, 尝试重新配置环境..."

            source "$vmc_sh"

            if [ ! -f "$START_SCRIPT" ]; then
                log_error "重新配置后仍未找到启动脚本"
                return 1
            fi
        fi
        bash "$START_SCRIPT" --remove
    fi


    docker exec -d "$container" bash -c 'sudo -E bash /mdrive/mdrive/scripts/cmd.sh && sudo supervisorctl start Dreamview'
    log_info "Supervisor status 和 Dreamview 已启动..."

    docker exec -d "$container" bash -c "/mdrive/mdrive/bin/mdrive_multiviz >/dev/null 2>&1"

    log_info "mdrive_multiviz 已启动..."

    # 打开浏览器
    nohup xdg-open http://localhost:9001 >/dev/null 2>&1 &
    sleep 1
    nohup xdg-open http://localhost:8888 >/dev/null 2>&1 &

    log_info "进入 Docker 容器: ${container}"
    bash ${mdrive_root}/mdrive/docker/dev_into.sh
}

# ================= 主流程 =================
find_version_path
show_git_info
sync_local_env
enter_docker
