#!/bin/bash
# 自动续传脚本
while true; do
    echo "--- 传输开始时间: $(date) ---" >> ~/rsync_log.txt
    rsync -avhP --timeout=60 --bwlimit=20000 --inplace ~/AM_R_Offset /media/nas/04.mdrive3/01.road_test/XZB600012/2025/20251223 >> ~/rsync_log.txt 2>&1

    # 检查 rsync 的退出码，0 表示传输完全成功
    if [ $? -eq 0 ]; then
        echo "✅ 传输完美完成！" >> ~/rsync_log.txt
        break
    else
        echo "⚠️ 传输中断，5秒后自动重试续传..." >> ~/rsync_log.txt
        sleep 5
    fi
done
