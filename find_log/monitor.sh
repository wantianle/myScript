#!/bin/bash

# --- 配置区 ---
# 监控的 Topic 和预期的最低频率阈值 (Hz)
TOPIC_PERCEPTION="/apollo/perception/obstacles"
THRESHOLD_PERC=8
TOPIC_LOC="/apollo/localization/pose"
THRESHOLD_LOC=45

# 数据存放路径
SOURCE_DIR="/apollo/data/recorder"
SAVE_DIR="/apollo/data/issue_captured"
mkdir -p $SAVE_DIR

echo "Sentry: 开始监控系统频率... (按下 Ctrl+C 停止)"

# --- 监控循环 ---
while true; do
    # 1. 获取感知模块当前频率
    # 使用 cyber_monitor 的非交互模式或通过 hz 指令
    curr_perc_hz=$(cyber_channel echo $TOPIC_PERCEPTION -n 1 | grep "hz" | awk '{print $NF}' | cut -d'.' -f1)

    # 2. 获取定位模块当前频率
    curr_loc_hz=$(cyber_channel echo $TOPIC_LOC -n 1 | grep "hz" | awk '{print $NF}' | cut -d'.' -f1)

    # 3. 逻辑判断
    trigger=false
    reason=""

    if [[ -n "$curr_perc_hz" && "$curr_perc_hz" -lt "$THRESHOLD_PERC" ]]; then
        trigger=true
        reason="Perception_Drop_${curr_perc_hz}Hz"
    elif [[ -n "$curr_loc_hz" && "$curr_loc_hz" -lt "$THRESHOLD_LOC" ]]; then
        trigger=true
        reason="Localization_Drop_${curr_loc_hz}Hz"
    fi

    # 4. 触发采集
    if [ "$trigger" = true ]; then
        timestamp=$(date +%Y%m%d_%H%M%S)
        echo "🚨 检测到异常: $reason ! 正在采集证据..."

        target_path="$SAVE_DIR/issue_$timestamp"
        mkdir -p $target_path

        # 拷贝最近 2 个 record 文件（假设你的 recorder 在后台循环录制）
        ls -dt $SOURCE_DIR/*.record.* | head -n 2 | xargs -I {} cp {} $target_path/

        # 记录触发时的系统快照
        echo "Reason: $reason" > $target_path/report.txt
        top -b -n 1 | head -n 20 > $target_path/cpu_usage.txt

        echo "✅ 证据已保存至 $target_path"
        sleep 10 # 冷却时间，防止短时间内重复触发
    fi

    sleep 1 # 每秒检测一次
done
