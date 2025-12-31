#!/bin/bash

# ================= 配置部分 =================
set -Eeuo pipefail
LOG_SHOW_TIME=0
# SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# source "${SCRIPT_DIR}/common/logger.sh"
# ===========================================
# 日志时间戳颜色
LOG_SHOW_TIME="${LOG_SHOW_TIME:-1}"
log_prefix() {
    if [ "$LOG_SHOW_TIME" = "1" ]; then
        printf "[%s] " "$(date "+%Y-%m-%d %H:%M:%S")"
    fi
}

NC='\033[0m'
RED='\033[0;31m'
GREEN='\033[0;32m'
if [ ! -t 1 ]; then
    RED= GREEN= YELLOW= BLUE= GRAY= NC=
fi
log_info() {
    printf "%s[INFO] %s\n" "$(log_prefix)" "$*"
}
log_ok() {
    printf "${GREEN}%s[OK] %s${NC}\n" "$(log_prefix)" "$*"
}
log_error() {
    printf "${RED}%s[ERROR] %s${NC}\n" "$(log_prefix)" "$*"
}
# 初始化变量
target_root="/home/mini"
mount_root="/media/nas"
vehicle=""
target_date=""
custom_path=""
lookback=2 # 默认回溯1个片段
target_soc="soc1"
# 解析命令行参数
while getopts "v:t:p:m:s:" opt; do
    case $opt in
        v) vehicle="$OPTARG" ;;
        t) target_date="$OPTARG" ;;
        p) custom_path="$OPTARG" ;;
        m) lookback="$OPTARG" ;;
        s) target_soc="$OPTARG" ;;
        *) echo "Usage: $0 -v <vehicle> -t <date> [-p <local_path>] [-m <minutes>] [-s <soc>]"; exit 1 ;;
    esac
done

if [ -z "$target_date" ]; then
    log_error "Missing required parameters! 缺少日期参数"
    exit 1
fi

if [ ! -d "$custom_path" ] && [ -z "$vehicle" ]; then
    log_error "Missing required parameters! 缺少指定路径或指定车辆ID"
    exit 1
fi
# ================= 输出文件目录 =================
if [ -d "$HOME/Documents" ]; then
    OUTPUT_DIR="$HOME/Documents"
elif [ -d "$HOME/文档" ]; then
    OUTPUT_DIR="$HOME/文档"
fi

record_output_file="${OUTPUT_DIR}/${vehicle:-test}_${target_date}_record.txt"
tag_output_file="${OUTPUT_DIR}/${vehicle:-test}_${target_date}_tag.txt"

> "$record_output_file"
> "$tag_output_file"

# ================= 确定查询模式 =================
local_mode=0

if [ -n "$custom_path" ]; then
    base_dir="${custom_path%/}"
    local_mode=1
    log_info "Local Path Scan: $base_dir"
else
    base_dir="${mount_root}/04.mdrive3/01.road_test/${vehicle}/${target_date:0:4}/${target_date}"
    local_mode=0
    log_info "Nas Path Scan: $base_dir"
fi

if [ ! -d "$base_dir" ]; then
    log_error "Base directory not found: $base_dir"
    exit 1
fi


# ================= 建立 Record 索引 (精确到秒) =================
declare -A records
shopt -s nullglob

# ${bash_dir}/20251220 112907.record.00000.112907
while IFS= read -r -d '' record_path; do
    record_time="${record_path##*.}"
    if [[ "$record_time" =~ ^[0-9]{6}$ ]]; then
        hh=${record_time:0:2}
        mm=${record_time:2:2}
        ss=${record_time:4:2}
        seconds=$(( 10#$hh * 3600 + 10#$mm * 60 + 10#$ss ))
        minutes=$(( 10#$hh * 60 + 10#$mm ))

        # 存储格式: "总秒数|路径"
        if [[ -v records[$minutes] ]]; then
            records[$minutes]="${records[$minutes]} ${seconds}|${record_path}"
        else
            records[$minutes]="${seconds}|${record_path}"
        fi
    fi
done < <(find "$base_dir" \
            -type f \
            -path "*${target_soc}*" \
            -name "${target_date}*record*" \
            -print0)

log_info "Find record files Successful! Finding records before tag time..."
# --- 新增：用于存储待复制任务的数组 ---
copy_tasks=()
# ================= 处理 Tag 文件 =================
tag_files=$(find "$base_dir" -name "tag_${target_date}*.pb.txt" -type f)

if [[ -z "$tag_files" ]]; then
    log_error "No tag files found in $BASE_DIR"
    exit 1
fi

for tag_file in $tag_files; do
    while IFS= read -r line; do
        if [[ $line =~ msg:\ \"([^\"]+)\" ]]; then
            msg="${BASH_REMATCH[1]//\\n/}"
            result=""
            is_error=0

            hh="" mm="" ss=""
            # 解析时间 (支持 24h 和 12h AM/PM 格式)
            if [[ $msg =~ ([0-9]{4}/[0-9]{1,2}/[0-9]{1,2}\ ([0-9]{1,2}):([0-9]{2}):([0-9]{2})) ]]; then
                hh=${BASH_REMATCH[2]}; mm=${BASH_REMATCH[3]}; ss=${BASH_REMATCH[4]}
            elif [[ $msg =~ ([0-9]{1,2}/[0-9]{1,2}/[0-9]{4}),\ ([0-9]{1,2}):([0-9]{2}):([0-9]{2})\ (AM|PM) ]]; then
                hh=${BASH_REMATCH[2]}; mm=${BASH_REMATCH[3]}; ss=${BASH_REMATCH[4]}; ampm=${BASH_REMATCH[5]}
                [[ "$ampm" == "PM" ]] && (( hh < 12 )) && (( hh += 12 ))
            fi

            msg_seconds=$(( 10#$hh * 3600 + 10#$mm * 60 + 10#$ss ))
            msg_minutes=$(( 10#$hh * 60 + 10#$mm ))

            matched_files_raw=""
            # 回溯查找
            for (( m=0; m<=lookback; m++ )); do
                target_min=$((msg_minutes - m))
                if [[ -n "${records[$target_min]:-}" ]]; then
                    matched_files_raw="${matched_files_raw} ${records[$target_min]}"
                fi
            done

            # 精确筛选
            matched_files=""
            for item in $matched_files_raw; do
                f_sec="${item%%|*}"
                f_path="${item#*|}"
                if [ $f_sec -le $msg_seconds ]; then
                    matched_files="${matched_files} ${f_sec}|${f_path}"
                fi
            done

            if [ -n "$matched_files" ]; then
                result=$(echo "$matched_files" | tr ' ' '\n' | sort -n | tail -n "$lookback" | cut -d'|' -f2 | tr '\n' ' ')
            else
                is_error=1
            fi


            # 输出部分
            if(( is_error )); then
                log_error "$msg ==> 找不到对应 record 文件，请检查是否存在或增加回溯片段数！"
            else
                log_ok "$msg"
                read -r -a file_array <<< "$result"
                dir_path="${file_array[0]%/*}"
                file_names=""
                for f in "${file_array[@]}"; do
                    name="${f##*/}"
                    file_names+=" $name"
                done
                echo "[目录]: $dir_path"
                echo "[文件]: ${file_names# }"
                echo "[回播命令]:"
                echo "cyber_recorder play -l -f $result"
                # --- 新增：保存有效任务到数组 ---
                copy_tasks+=("${msg}|${result}")
            fi

            echo ""
            { echo "$msg"; echo "$result"; echo ""; } >> "$record_output_file"
            echo "$msg" >> "$tag_output_file"
        fi
    done < "$tag_file"
done

log_ok "1. record 路径文件: $record_output_file"
log_ok "2. tag 文件: $tag_output_file"

# ================= 复制分类 tag 对应的 record 文件 =================

read -n 1 -r -p "$(echo -e "\n\033[33m按 tag 分类复制 record 文件到\"${target_root}/${target_date}\"? (y/Y or quit)\033[0m") " user_input
echo
[[ ! $user_input =~ ^[Yy]$ ]] && exit 0
if [ ${#copy_tasks[@]} -eq 0 ]; then
    log_info "没有查找到符合条件的 record 文件！"
    exit 1
fi
# --- 人类可读格式 ---
human_size() {
    numfmt --to=iec --format="%.2f" "$1"
}

# --- 分行绘制单个 Task 进度条 ---
task_progress() {
    local current_bytes=$1 total_bytes=$2 tag=$3 status=$4

    [ "$total_bytes" -le 0 ] && total_bytes=1
    local percent=$(( current_bytes * 100 / total_bytes ))

    # 进度条长度 (缩短一点防止窄屏换行)
    local bar_size=20
    local filled=$(( percent * bar_size / 100 ))
    local empty=$(( bar_size - filled ))

    local bar; bar=$(printf "%${filled}s" | tr ' ' '#')
    local space; space=$(printf "%${empty}s" | tr ' ' '-')

    # 定义颜色转义码 (使用 \e 提高兼容性)
    local YELLOW="\e[33m"
    local GREEN="\e[32m"
    local END="\e[0m"

    local label="${YELLOW}[同步中]${END}"
    [[ "$status" == "done" ]] && label="${GREEN}[已完成]${END}"

    # 使用 %b 来确保颜色转义字符被解析
    printf "\r\e[K%b %-20.20s [%b%b] %3d%% (%s/%s)" \
        "$label" "$tag" "${GREEN}$bar${END}" "${GREEN}$space${END}" "$percent" "$(human_size $current_bytes)" "$(human_size $total_bytes)"
}

# --- 第一阶段：任务预检 ---
log_info "正在预检磁盘空间并规划任务..."

declare -A name_count
declare -a final_tasks
overall_total_bytes=0

for task in "${copy_tasks[@]}"; do
    raw_msg="${task%%|*}"
    file_list="${task#*|}"
    # 取tag内容替换文件系统非法字符和前后空格
    base_name=$(echo "${raw_msg%%:*}" | sed 's/[/\\:*?"<>|]//g' | xargs)
    base_name=${base_name:-nulltag}

    # 智能重命名逻辑
    if [[ ! -v name_count["$base_name"] ]]; then
        name_count["$base_name"]=1
        final_name="$base_name"
    else
        idx=${name_count["$base_name"]}
        final_name="${base_name}$idx"
        name_count["$base_name"]=$((idx + 1))
    fi

    task_total_bytes=0
    task_files_data=""
    for f in $file_list; do
        if [ -f "$f" ]; then
            f_size=$(stat -c %s "$f")
            task_total_bytes=$((task_total_bytes + f_size))
            task_files_data+="${f}:${f_size} "

            v_json="$(dirname "$f")/version.json"
            [ -f "$v_json" ] && task_total_bytes=$((task_total_bytes + $(stat -c %s "$v_json")))
        fi
    done

    if [ -n "$task_files_data" ]; then
        final_tasks+=("${final_name}|${task_total_bytes}|${task_files_data}")
        overall_total_bytes=$((overall_total_bytes + task_total_bytes))
    fi
done
# 空间对比
avail_space=$(df -B1 "${target_root}" | awk 'NR==2 {print $4}')
if [ "$overall_total_bytes" -gt "$avail_space" ]; then
    log_error "空间不足！需 $(human_size $overall_total_bytes), 可用 $(human_size $avail_space)"; exit 1
fi
# --- 分行执行同步 ---
for task in "${final_tasks[@]}"; do
    IFS='|' read -r t_name t_total_bytes t_files_info <<< "$task"

    # 获取目标路径
    first_pair=$(echo "$t_files_info" | awk '{print $1}')
    first_f="${first_pair%%:*}"
    soc_dir_name=$(basename "$(dirname "$first_f")")
    dest_path="${target_root}/${target_date}/${t_name}/${soc_dir_name}"
    mkdir -p "$dest_path"

    # 1. 增量清理 (Sync)
    declare -A expected
    expected["version.json"]=1
    for pair in $t_files_info; do expected["$(basename "${pair%%:*}")"]=1; done
    for existing in "$dest_path"/*; do
        [ -e "$existing" ] || continue
        [[ ! -v expected["$(basename "$existing")"] ]] && rm -f "$existing"
    done

    # 2. 复制片段
    current_task_done_bytes=0
    read -r -a pairs <<< "$t_files_info"
    for pair in "${pairs[@]}"; do
        src="${pair%%:*}"
        src_size="${pair##*:}"
        fname=$(basename "$src")
        target_file="$dest_path/$fname"

        # 断点续传
        if [ -f "$target_file" ] && [ "$(stat -c %s "$target_file")" -eq "$src_size" ]; then
            current_task_done_bytes=$((current_task_done_bytes + src_size))
        else
            cp "$src" "$target_file" &
            cp_pid=$!
            while kill -0 $cp_pid 2>/dev/null; do
                written=$(stat -c %s "$target_file" 2>/dev/null || echo 0)
                task_progress "$((current_task_done_bytes + written))" "$t_total_bytes" "$t_name" "copying"
                sleep 0.1
            done
            wait $cp_pid
            current_task_done_bytes=$((current_task_done_bytes + src_size))
        fi

        # 处理 version.json
        v_src="$(dirname "$src")/version.json"
        if [ -f "$v_src" ] && [ ! -f "$dest_path/version.json" ]; then
            cp "$v_src" "$dest_path/version.json"
            v_size=$(stat -c %s "$v_src")
            current_task_done_bytes=$((current_task_done_bytes + v_size))
        fi
    done

    # 该 Tag 完成后强制打印 100% 并真正换行
    task_progress "$t_total_bytes" "$t_total_bytes" "$t_name" "done"
    echo
done

log_ok "同步完成，总大小: $(human_size $overall_total_bytes)"
