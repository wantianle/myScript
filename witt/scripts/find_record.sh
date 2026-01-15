#!/bin/bash

set -Eeuo pipefail
source "${BASH_SOURCE[0]%/*}/utils.sh"
trap 'failure ${BASH_SOURCE[0]} $LINENO "$BASH_COMMAND"' ERR

# ================= 确定查询模式 =================
if [[ $MODE == "3" ]]; then
    data_dir="$REMOTE_DATA_ROOT"
    log_info "远程模式: $REMOTE_USER@$REMOTE_IP:$data_dir"
    ssh_cmd() {
        # 确保 socket 目录存在（建议放在 /tmp 下，重启会自动清理）
        mkdir -p /tmp/ssh_mux
        LC_ALL=C LANG=C ssh -o ConnectTimeout=3 \
            -o StrictHostKeyChecking=no \
            -o UserKnownHostsFile=/dev/null \
            -o LogLevel=ERROR \
            -o ControlMaster=auto \
            -o ControlPath=/tmp/ssh_mux/%r@%h:%p \
            -o ControlPersist=5m \
            "$REMOTE_USER@$REMOTE_IP" "LC_ALL=C $@"
}
elif [[ $MODE == "2" ]]; then
    data_dir="${NAS_ROOT}/${TARGET_DATE:0:8}/${VEHICLE}"
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
find_cmd="find \"$data_dir\" -type f \( \( -path '*${SOC}*' -name '${TARGET_DATE}*record*' \) -o -name 'tag_${TARGET_DATE}*.pb.txt' \) 2>/dev/null"

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
[[ -z "$tag_list" ]] && { log_error "$data_dir 找不到对应的 tag 文件！"; exit 1; }

for tag_file in $tag_list; do
    if [[ $MODE == "3" ]]; then
        content=$(ssh_cmd "cat $tag_file")
    else
        content=$(cat "$tag_file")
    fi

    while IFS= read -r line; do
        if [[ $line =~ msg:\ \"([^\"]+)\" ]]; then
            msg="${BASH_REMATCH[1]//\\n/}"
            tag="${msg%% :*}"
            yyyy="" month="" dd="" hh="" mm="" ss=""
            if [[ $msg =~ ([0-9]{4})/([0-9]{1,2})/([0-9]{1,2})\ ([0-9]{1,2}):([0-9]{2}):([0-9]{2}) ]]; then
                yyyy=${BASH_REMATCH[1]}; month=${BASH_REMATCH[2]}; dd=${BASH_REMATCH[3]}
                hh=${BASH_REMATCH[4]}; mm=${BASH_REMATCH[5]}; ss=${BASH_REMATCH[6]}
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

            start_sec=$((msg_seconds - BEFORE))
            end_sec=$((msg_seconds + AFTER))
            start_min=$(((start_sec - 60) / 60))
            end_min=$((end_sec / 60))

            matched_files=""
            for (( m=start_min; m<=end_min; m++ )); do
                if [[ -n "${records[$m]:-}" ]]; then
                    matched_files="${matched_files} ${records[$m]}"
                fi
            done
           # 精确筛选
            if [[ -n "$matched_files" ]]; then
                sorted_candidates=$(echo "$matched_files" | tr ' ' '\n' | sort - -n)
                final_list=""
                last_file=""

                while read -r line; do
                    [[ -z "$line" ]] && continue
                    f_sec="${line%%|*}"
                    f_path="${line#*|}"

                    if (( f_sec >= end_sec )); then
                        continue
                    fi
                    # 如果文件起始时间在请求区间内，加入 final_list
                    if (( f_sec >= start_sec )); then
                        final_list="${final_list} ${f_path}"
                    # 如果文件起始时间早于请求开始时间，它可能是包含这段数据的那个“母文件”
                    else
                        last_file="$f_path"
                    fi
                done <<< "$sorted_candidates"
                result="${last_file} ${final_list}"
                result=$(echo "$result" | xargs)
            else
                result=""
            fi
            all_tasks+=("${formatted_time}|${tag}|${result}")
        fi
    done <<< "$content"
done

if [[ ${#all_tasks[@]} -gt 0 ]]; then
    mapfile -t sorted_tasks < <(printf "%s\n" "${all_tasks[@]}" | sort -t'|' -k1,1)
    all_tasks=()
    error_tasks=()
    count=0

    for task_line in "${sorted_tasks[@]}"; do
        tag_time="${task_line%%|*}"
        tmp="${task_line#*|}"
        tag_name="${tmp%%|*}"
        tag_paths="${tmp#*|}"
        count=$((count + 1))
        all_tasks+=("${tag_time}|${tag_name}|${tag_paths}")
        read -r -a t_paths <<< "${tag_paths}"
        if [[ ${#t_paths[@]} -gt 0 ]]; then
            t_dir="${t_paths[0]%/*}"
            t_files=""
            for f in "${t_paths[@]}"; do t_files+=" ${f##*/}"; done
            echo -e "${GREEN}[$count] $tag_name : $tag_time${NC}"
            echo "[目录]: $t_dir"
            echo "[文件]: ${t_files# }"
            echo "cyber_recorder play -l -f ${tag_paths}"
            echo "------------------------------------------------"
        else
            error_tasks+=("[$count] $tag_name : $tag_time")
        fi
    done
    if [[ ${#error_tasks[@]} -gt 0 ]]; then
        log_error "以下 tag 无法找到对应 record 数据"
        printf "%s\n" "${error_tasks[@]}"
        echo "------------------------------------------------"
    fi
else
    log_error "未找到到任何有效 record"
fi
printf "%s\n" "${all_tasks[@]}" > "$MANIFEST_PATH"
