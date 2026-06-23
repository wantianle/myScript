#!/bin/bash
set -e

# 用法: ./deploy.sh <port>
# 示例: ./deploy.sh 32639

if [ -z "$1" ]; then
    echo "用法: $0 <port>"
    echo "示例: $0 32639"
    exit 1
fi

PORT=$1
REMOTE_USER="nvidia"
REMOTE_HOST="ad.minieye.tech"

TARGET="${REMOTE_USER}@${REMOTE_HOST}"

echo ">>> 部署到 ${TARGET}:${PORT} ..."

# 0. 创建远程目录
echo "[0/5] 创建远程目录"
ssh -p "$PORT" "$TARGET" "mkdir -p /mdrive/mdrive_conf/modules/dreamview /mdrive/mdrive_conf/supervisor/soc1/conf /mdrive/mdrive_conf/supervisor/ipc/conf /mdrive/mdrive/bin"

# 1. conf 文件
echo "[1/5] 上传 ECAR_HW4/conf/*"
scp -r -P "$PORT" ./ECAR_HW4/conf/* "${TARGET}:/mdrive/mdrive_conf/modules/dreamview/"

# 2. supervisor/soc1 文件
echo "[2/5] 上传 ECAR_HW4/supervisor/soc1/*"
scp -r -P "$PORT" ./ECAR_HW4/supervisor/soc1/* "${TARGET}:/mdrive/mdrive_conf/supervisor/soc1/conf/"

# 3. supervisor/ipc 文件
echo "[3/5] 上传 ECAR_HW4/supervisor/ipc/*"
scp -r -P "$PORT" ./ECAR_HW4/supervisor/ipc/* "${TARGET}:/mdrive/mdrive_conf/supervisor/ipc/conf/"

# 4. www 目录
echo "[4/5] 上传 www/"
scp -r -P "$PORT" ./www "${TARGET}:/mdrive/mdrive/"

# 5. 可执行文件
echo "[5/5] 上传 mdrive_dreamview"
scp -P "$PORT" ./mdrive_dreamview "${TARGET}:/mdrive/mdrive/bin/"

echo ">>> 部署完成"
