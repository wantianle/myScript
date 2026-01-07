#!/bin/bash

set -Eeuo pipefail
LOG_SHOW_TIME=0
source "${BASH_SOURCE[0]%/*}/../utils/logger.sh"
while getopts "v:t:l:s:b:f:" opt; do
    case $opt in
        v) vehicle="$OPTARG" ;;
        t) target_date="$OPTARG" ;;
        l) manifest_file="$OPTARG" ;;
        s) soc="$OPTARG" ;;
        b) lookback="$OPTARG" ;;
        f) lookfront="$OPTARG" ;;
        *) exit 1 ;;
    esac
done

if [[ -z "$target_date" ]]; then
    log_error "缺少日期参数！"
    exit 1
fi

# ================= 确定查询模式 =================
if [[ $MODE == "3" ]]; then
    data_dir="$REMOTE_DATA_ROOT"
    log_info "远程模式: $REMOTE_USER@$REMOTE_IP:$data_dir"
    ssh_cmd() {
        LC_ALL=C LANG=C ssh -o ConnectTimeout=3 \
            -o StrictHostKeyChecking=no \
            -o UserKnownHostsFile=/dev/null \
            -o LogLevel=ERROR \
            "$REMOTE_USER@$REMOTE_IP" "LC_ALL=C $@"
    }
elif [[ $MODE == "2" ]]; then
    [[ -z $vehicle ]] && { log_error "NAS 模式缺少车辆 ID (-v)"; exit 1; }
    data_dir="${NAS_ROOT}/${vehicle}/${target_date:0:4}/${target_date}"
    log_info "NAS 模式: $data_dir"
else
    if [ ! -d $LOCAL_PATH ]; then
        log_error "错误: $LOCAL_PATH 不是一个目录或不存在: sudo mkdir $LOCAL_PATH"
        exit 1
    elif [ ! -w $LOCAL_PATH ] || [ ! -x $LOCAL_PATH ]; then
        log_error "你没有足够的权限访问 $LOCAL_PATH, 请执行 sudo chown -R $USER:$USER $LOCAL_PATH"
        exit 1
    fi
    data_dir="${LOCAL_PATH%/}"
    log_info "本地路径模式: $data_dir"
fi
# ================= 建立 Record 索引 =================
declare -A records
shopt -s nullglob
find_cmd="find \"$data_dir\" -type f \( \( -path '*${soc}*' -name '${target_date}*record*' \) -o -name 'tag_${target_date}*.pb.txt' \) 2>/dev/null"

if [[ $MODE == "3" ]]; then
    raw_files=$(ssh_cmd "$find_cmd") || { log_error "无法连接车机或找不到对应record 文件！"; exit 1; }
else
    raw_files=$(eval "$find_cmd")
fi
record_list=$(echo "$raw_files" | grep record)
tag_list=$(echo "$raw_files" | grep tag)

# ${bash_dir}/20251220-112907.record.00000.112907
[[ -z "$record_list" ]] && { log_error "$data_dir 目录下找不到 record 文件！"; exit 1; }
while read -r record_path; do
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
done <<< "$record_list"

# ================= 处理 Tag 文件 =================
all_tasks=()
tag_counter=0
[[ -z "$tag_list" ]] && { log_error "$data_dir 找不到对应的 tag 文件！"; exit 1; }
for tag_file in $tag_list; do
    if [[ $MODE == "3" ]]; then
        content=$(ssh_cmd "cat $tag_file")
    else
        content=$(cat "$tag_file")
    fi
    while IFS= read -r line; do
        # msg: 变道过慢，打方向灯3s应该变道\n : 12/27/2025, 3:24:14 PM
        if [[ $line =~ msg:\ \"([^\"]+)\" ]]; then
            msg="${BASH_REMATCH[1]//\\n/}"
            tag="${msg%% :*}"
            result=""
            is_error=0

            yyyy="" month="" dd="" hh="" mm="" ss=""
            # 2025/12/23 14:27:27
            if [[ $msg =~ ([0-9]{4})/([0-9]{1,2})/([0-9]{1,2})\ ([0-9]{1,2}):([0-9]{2}):([0-9]{2}) ]]; then
                yyyy=${BASH_REMATCH[1]}; month=${BASH_REMATCH[2]}; dd=${BASH_REMATCH[3]}
                hh=${BASH_REMATCH[4]}; mm=${BASH_REMATCH[5]}; ss=${BASH_REMATCH[6]}
            # 12/23/2025, 2:27:27 PM
            elif [[ $msg =~ ([0-9]{1,2})/([0-9]{1,2})/([0-9]{4}),\ ([0-9]{1,2}):([0-9]{2}):([0-9]{2})\ (AM|PM) ]]; then
                month=${BASH_REMATCH[1]}; dd=${BASH_REMATCH[2]}; yyyy=${BASH_REMATCH[3]}
                hh=${BASH_REMATCH[4]}; mm=${BASH_REMATCH[5]}; ss=${BASH_REMATCH[6]}; ampm=${BASH_REMATCH[7]}
                [[ "$ampm" == "PM" ]] && (( 10#$hh < 12 )) && hh=$(( 10#$hh + 12 ))
                [[ "$ampm" == "AM" ]] && (( 10#$hh == 12 )) && hh="00"
            fi
            formatted_time=$(printf '%04d-%02d-%02d %02d:%02d:%02d' \
                    $((10#$yyyy)) $((10#$month)) $((10#$dd)) \
                    $((10#$hh)) $((10#$mm)) $((10#$ss)))

            msg_seconds=$(( 10#$hh * 3600 + 10#$mm * 60 + 10#$ss ))
            msg_minutes=$(( 10#$hh * 60 + 10#$mm ))

            # 秒级筛选
            matched_files_raw=""
            start_sec=$((msg_seconds - lookback))
            end_sec=$((msg_seconds + lookfront))
            start_min=$((start_sec / 60))
            end_min=$((end_sec / 60))

            matched_files_raw=""
            for (( m=start_min; m<=end_min; m++ )); do
                if [[ -n "${records[$m]:-}" ]]; then
                    matched_files_raw="${matched_files_raw} ${records[$m]}"
                fi
            done
            # 我们需要找的是：开始时间落在 [start_sec, end_sec] 之间的文件，以及“覆盖”了 start_sec 的那个前序文件
            matched_files=""
            for item in $matched_files_raw; do
                f_sec="${item%%|*}"
                f_path="${item#*|}"
                if (( f_sec <= end_sec )); then
                    matched_files="${matched_files} ${f_sec}|${f_path}"
                fi
            done
            # 精确过滤
            if [[ -n "$matched_files" ]]; then
                sorted_files=$(echo "$matched_files" | tr ' ' '\n' | sort -n)
                # 过滤：保留所有 f_sec >= start_sec 的文件
                # 加上“最后一个 f_sec < start_sec”的文件（因为它覆盖了起始时刻）
                final_list=""
                last_before_start=""
                while read -r line; do
                    [[ -z "$line" ]] && continue
                    this_f_sec="${line%%|*}"
                    if (( this_f_sec < start_sec )); then
                        last_before_start="$line"
                    else
                        final_list="${final_list} ${line}"
                    fi
                done <<< "$sorted_files"

                # 最终结果 = 覆盖起始的文件 + 范围内的文件
                result_raw="${last_before_start}${final_list}"
                result=$(echo "$result_raw" | tr ' ' '\n' | cut -d'|' -f2 | tr '\n' ' ')
            else
                log_warn "${formatted_time} ${tag} ==> 找不到对应 record 文件，请检查是否存在或改变筛选范围！"
                continue
            fi
            tag_counter=$((tag_counter + 1))
            echo -e "${GREEN}[$tag_counter] $tag : $formatted_time${NC}"
            read -r -a file_array <<< "${result}"
            dir="${file_array[0]%/*}"
            files=""
            for f in "${file_array[@]}"; do
                name="${f##*/}"
                files+=" $name"
            done
            echo "[目录]: $dir"
            echo "[文件]: ${files# }"
            echo "[回播命令]:"
            echo "cyber_recorder play -l -f ${result% }"
            all_tasks+=("${formatted_time}|${tag}|${result% }")
        fi
    done <<< "$content"
done

# ================= 序号选择逻辑 =================
(( ${#all_tasks[@]} == 0 )) && { log_info "没有查找到符合条件的 record 文件！"; exit 1; }
read -p "找到 $tag_counter 个 Tag，请输入要处理的序号 (例如 1,2,5 或输入 0 导出全部): " selection

copy_tasks=()
if [[ "$selection" == "0" ]]; then
    copy_tasks=("${all_tasks[@]}")
else
    IFS=',' read -ra selected_tasks <<< "$selection"
    for i in "${selected_tasks[@]}"; do
        idx=$(( $(echo "$i" | xargs) - 1 ))
        if (( idx >= 0 && idx < ${#all_tasks[@]} )); then
            copy_tasks+=("${all_tasks[$idx]}")
        else
            log_warn "无效序号: $((idx+1))，已忽略。"
        fi
    done
fi

if (( ${#copy_tasks[@]} == 0 )); then
    log_warn "未选择任何有效序号！"
    exit 0
fi
printf "%s\n" "${copy_tasks[@]}" > "$manifest_file"
