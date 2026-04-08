#!/usr/bin/env bash

set -Eeuo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/utils.sh"
trap 'failure ${BASH_SOURCE[0]} ${LINENO} "$BASH_COMMAND"' ERR
VMC_SH="$MDRIVE_ROOT/vmc.sh"

find_version() {
    content=""
    local input_data="$VERSION"
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
        localization_ver=$(awk '$1=="mdrive_map_localization" {print $2}' "$input_data")
    else
        log_info "使用指定的 version.json 文件: $input_data"
        content=$(cat "$input_data")
        mdrive_ver=$(echo "$content" | jq -r .mdrive)
        conf_ver=$(echo "$content" | jq -r .mdrive_conf)
        model_ver=$(echo "$content" | jq -r .mdrive_model)
        map_ver=$(echo "$content" | jq -r .mdrive_map)
        localization_ver=$(echo "$content" | jq -r .mdrive_map_localization)
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
    if [ -z "$mdrive_ver" ] || [ -z "$conf_ver" ]; then
        log_error "未能从文件中解析出 mdrive 或 mdrive_conf 版本"
        exit 1
    fi
}

sync_local_env() {
    log_info "同步本地环境..."
    local cur_vehicle_model=$(grep '^MDRIVE_VEHICLE_MODEL=' "$VMC_SH" | cut -d '"' -f2)
    local cur_vehicle=$(grep '^MDRIVE_VEHICLE_NAME=' "$VMC_SH" | cut -d '"' -f2)
    local cur_mdrive_ver=$(grep '^MDRIVE_VERSION=' "$VMC_SH" | cut -d '=' -f2)
    local cur_conf_ver=$(grep '^MDRIVE_CONF_VERSION=' "$VMC_SH" | cut -d '=' -f2)
    local cur_model_ver=$(grep '^MDRIVE_MODEL_VERSION=' "$VMC_SH" | cut -d '=' -f2)
    local cur_map_ver=$(grep '^MDRIVE_MAP_VERSION=' "$VMC_SH" | cut -d '=' -f2)
    if [ "$cur_vehicle_model" = "$vehicle_model" ] &&
       [ "$cur_vehicle" = "$VEHICLE" ] &&
       [ "$cur_mdrive_ver" = "$mdrive_ver" ] &&
       [ "$cur_conf_ver" = "$conf_ver" ] &&
       [ "$cur_model_ver" = "$model_ver" ] &&
       [ "$cur_map_ver" = "$map_ver" ]; then
        return
    fi
    sed -i -e "/^MDRIVE_VEHICLE_MODEL/c\MDRIVE_VEHICLE_MODEL=\"$vehicle_model\"" \
        -e "/^MDRIVE_VEHICLE_NAME/c\MDRIVE_VEHICLE_NAME=\"$VEHICLE\"" \
        -e "/^MDRIVE_VERSION/c\MDRIVE_VERSION=$mdrive_ver" \
        -e "/^MDRIVE_CONF_VERSION/c\MDRIVE_CONF_VERSION=$conf_ver" \
        -e "/^MDRIVE_MODEL_VERSION/c\MDRIVE_MODEL_VERSION=$model_ver" \
        -e "/^MDRIVE_MAP_VERSION/c\MDRIVE_MAP_VERSION=$map_ver" "$VMC_SH"
    source "$VMC_SH"
}

find_version
sync_local_env
