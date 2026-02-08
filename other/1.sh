#!/bin/bash

NAS="hfs.minieye.tech"
MOUNT_POINT="/media/mini"

# if grep -qs "$MOUNT_POINT" /proc/mounts; then
#     # grep -qs "$MOUNT_POINT" /proc/mounts
#     MOUNTED=0 # 没挂上
# else
#     # grep -qs "$MOUNT_POINT" /proc/mounts
#     MOUNTED=1 # 挂上了
# fi
# if ping -c 1 -W 10 $NAS >/dev/null 2>&1; then
#     # if [[ $MOUNTED -eq 1 ]]; then
#     #     echo "网络断开，执行延迟卸载..."
#     # fi
#     echo 0
# else
#     # if [[ $MOUNTED -eq 0 ]]; then
#     #     echo "网络已通，尝试挂载 NAS..."
#     # fi
#     echo 1
# fi


# if grep -qs "$MOUNT_POINT" /proc/mounts; then
#     # grep -qs "$MOUNT_POINT" /proc/mounts
#     echo 0 # 没挂上
# else
#     # grep -qs "$MOUNT_POINT" /proc/mounts
#     echo 1 # 挂上了
# fi

ONLINE=1 # 默认离线
if ping -c 2 -W 3 172.168.10.2 >/dev/null 2>&1 || timeout 2 bash -c "</dev/tcp/$NAS/445" >/dev/null 2>&1; then
    ONLINE=0 # 在线
    echo $ONLINE
fi
