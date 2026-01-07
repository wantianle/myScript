#!/usr/bin/env bash

###############################################################################
# Copyright 2025 The MINIEYE L4 Team. All Rights Reserved.
#
###############################################################################

# $HOME/project/vmc.sh
set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
VMC_CMD="${HOME}/.vmc/bin/vmc"

export VMC_HOME="${HOME}/.vmc"
export VMC_SOFTWARE="${ROOT_DIR}"
export VMC_PLATFORM="amd64"
# 配置最大缓存，单位：MB
export VMC_CACHE_MAX_SIZE=10240

# 包配置
MDRIVE_VEHICLE_MODEL=""
MDRIVE_VEHICLE_NAME=""
MDRIVE_VEHICLE_ID=""
MDRIVE_VERSION=""
MDRIVE_CONF_VERSION=""
MDRIVE_MODEL_VERSION=""
MDRIVE_MAP_VERSION=""


# 安装
export MDRIVE_VEHICLE_MODEL="${MDRIVE_VEHICLE_MODEL}"
export MDRIVE_VEHICLE_NAME="${MDRIVE_VEHICLE_NAME}"
export MDRIVE_VEHICLE_ID="${MDRIVE_VEHICLE_ID}"

${VMC_CMD} install --name mdrive --version ${MDRIVE_VERSION}
${VMC_CMD} install --name mdrive_conf  --version ${MDRIVE_CONF_VERSION}
${VMC_CMD} install --name mdrive_model --version ${MDRIVE_MODEL_VERSION}
${VMC_CMD} install --name mdrive_map  --version ${MDRIVE_MAP_VERSION}

bash ${VMC_SOFTWARE}/mdrive/docker/dev_start.sh  --remove
