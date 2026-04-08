#!/usr/bin/env bash
# ==============================================================================
# 脚本名称: patch.sh
# 适用环境: Ubuntu (Xorg/Wayland), NVIDIA GPU, Mdrive Container
# 功能描述: 为 dev_start.sh 打入 Wayland + NVIDIA 兼容性补丁
# ==============================================================================

TARGET_SCRIPT="/home/mini/project/mdrive/docker/dev_start.sh"

if [ ! -f "$TARGET_SCRIPT" ]; then
    echo "错误: 找不到 $TARGET_SCRIPT"
    exit 1
fi

# 定义检测函数
check_wayland_nvidia() {
    local is_wayland=false
    local is_nvidia=false

    # 1. 检测桌面协议
    if [[ "$XDG_SESSION_TYPE" == "wayland" ]]; then
        is_wayland=true
    fi

    # 2. 检测当前 OpenGL 渲染器 (需要 mesa-utils)
    # 如果没装 glxinfo，降级使用 lspci 检测显卡硬件
    if command -v glxinfo >/dev/null 2>&1; then
        if glxinfo | grep -iq "NVIDIA"; then
            is_nvidia=true
        fi
    else
        if lspci | grep -iq "VGA.*NVIDIA"; then
            is_nvidia=true
        fi
    fi
    if [[ "$is_wayland" == true && "$is_nvidia" == true ]]; then
        return 0
    else
        return 1
    fi
}

if check_wayland_nvidia; then
    printf "\033[0;33m[WARN] %s\033[0m\n" "正在为 $TARGET_SCRIPT 打入 Wayland + NVIDIA 兼容性补丁..."

    # 1. 在 mount_local_volumes 函数中注入 XAUTHORITY 挂载
    # 匹配 /tmp/.X11-unix 并在其后添加挂载行
    sed -i '/-v \/tmp\/.X11-unix:\/tmp\/.X11-unix:rw/a \        -v ${XAUTHORITY}:/tmp/.Xauthority:ro \\' "$TARGET_SCRIPT"

    # 2. 在 start_container 函数中注入 XAUTHORITY 环境变量
    # 匹配 -e DISPLAY并在其后添加环境变量行
    sed -i '/-e DISPLAY="${display}"/a \        -e XAUTHORITY="/tmp/.Xauthority" \\' "$TARGET_SCRIPT"
fi
