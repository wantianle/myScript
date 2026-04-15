#!/usr/bin/env bash
# ==============================================================================
# 脚本名称: restore_runtime_env.sh
# 功能描述: 根据 VERSION 输入同步本地 mdrive 运行环境配置
# ==============================================================================

set -Eeuo pipefail
readonly DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
readonly VMC_SH="$MDRIVE_ROOT/vmc.sh"
source "$DIR/utils.sh"

trap 'failure ${BASH_SOURCE[0]} ${LINENO} "$BASH_COMMAND"' ERR

resolve_version_info() {
    local version_input="$VERSION"
    local version_content=""

    if [[ ! -f "$version_input" ]]; then
        log_error "文件不存在: $version_input"
        exit 1
    fi

    if [[ "$version_input" =~ .*\.txt$ ]]; then
        log_info "使用指定的 version.txt 文件: $version_input"
        mdrive_ver=$(awk '$1=="mdrive" {print $2}' "$version_input")
        conf_ver=$(awk '$1=="mdrive_conf" {print $2}' "$version_input")
        model_ver=$(awk '$1=="mdrive_model" {print $2}' "$version_input")
        map_ver=$(awk '$1=="mdrive_map" {print $2}' "$version_input")
        localization_ver=$(awk '$1=="mdrive_map_localization" {print $2}' "$version_input")
    else
        log_info "使用指定的 version.json 文件: $version_input"
        version_content=$(cat "$version_input")
        mdrive_ver=$(echo "$version_content" | jq -r .mdrive)
        conf_ver=$(echo "$version_content" | jq -r .mdrive_conf)
        model_ver=$(echo "$version_content" | jq -r .mdrive_model)
        map_ver=$(echo "$version_content" | jq -r .mdrive_map)
        localization_ver=$(echo "$version_content" | jq -r .mdrive_map_localization)
    fi

    vehicle_model=$(echo "$conf_ver" | cut -d'.' -f1)
    echo "------------------------------------------"
    echo "解析得到的版本信息:"
    echo "mdrive:             $mdrive_ver"
    echo "mdrive_conf:        $conf_ver"
    echo "mdrive_model:       $model_ver"
    echo "mdrive_map:         $map_ver"
    echo "mdrive_map_localization: $localization_ver"
    echo "vehicle_model:      $vehicle_model"
    echo "------------------------------------------"

    if [[ -z "$mdrive_ver" || -z "$conf_ver" ]]; then
        log_error "未能从文件中解析出 mdrive 或 mdrive_conf 版本"
        exit 1
    fi
}

sync_runtime_environment() {
    log_info "同步本地环境..."
    local current_vehicle_model
    local current_vehicle_name
    local current_mdrive_ver
    local current_conf_ver
    local current_model_ver
    local current_map_ver

    current_vehicle_model=$(grep '^MDRIVE_VEHICLE_MODEL=' "$VMC_SH" | cut -d '"' -f2)
    current_vehicle_name=$(grep '^MDRIVE_VEHICLE_NAME=' "$VMC_SH" | cut -d '"' -f2)
    current_mdrive_ver=$(grep '^MDRIVE_VERSION=' "$VMC_SH" | cut -d '=' -f2)
    current_conf_ver=$(grep '^MDRIVE_CONF_VERSION=' "$VMC_SH" | cut -d '=' -f2)
    current_model_ver=$(grep '^MDRIVE_MODEL_VERSION=' "$VMC_SH" | cut -d '=' -f2)
    current_map_ver=$(grep '^MDRIVE_MAP_VERSION=' "$VMC_SH" | cut -d '=' -f2)

    if [[ "$current_vehicle_model" = "$vehicle_model" ]] &&
       [[ "$current_vehicle_name" = "$VEHICLE" ]] &&
       [[ "$current_mdrive_ver" = "$mdrive_ver" ]] &&
       [[ "$current_conf_ver" = "$conf_ver" ]] &&
       [[ "$current_model_ver" = "$model_ver" ]] &&
       [[ "$current_map_ver" = "$map_ver" ]]; then
        return
    fi

    sed -i \
        -e "/^MDRIVE_VEHICLE_MODEL/c\MDRIVE_VEHICLE_MODEL=\"$vehicle_model\"" \
        -e "/^MDRIVE_VEHICLE_NAME/c\MDRIVE_VEHICLE_NAME=\"$VEHICLE\"" \
        -e "/^MDRIVE_VERSION/c\MDRIVE_VERSION=$mdrive_ver" \
        -e "/^MDRIVE_CONF_VERSION/c\MDRIVE_CONF_VERSION=$conf_ver" \
        -e "/^MDRIVE_MODEL_VERSION/c\MDRIVE_MODEL_VERSION=$model_ver" \
        -e "/^MDRIVE_MAP_VERSION/c\MDRIVE_MAP_VERSION=$map_ver" \
        "$VMC_SH"
    source "$VMC_SH"
}

resolve_version_info
sync_runtime_environment
