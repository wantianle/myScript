#!/bin/bash

set -Eeuo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/utils.sh"
trap 'failure ${BASH_SOURCE[0]} $LINENO "$BASH_COMMAND"' ERR

# ================= 确定查询模式 =================
if findmnt -nt cifs "$DATA_ROOT" > /dev/null; then
    data_root="${NAS_ROOT}/${TARGET_DATE:0:8}/${VEHICLE}"
    log_info "NAS 模式: $data_root"
else
    data_root="${DATA_ROOT%/}"
    log_info "本地路径模式: $data_root"
fi
# ================= 建立 Record 索引 =================
declare -A records
shopt -s nullglob
find_cmd="find \"$data_root\" -type f \( \( -path '*${SOC}*' -name '${TARGET_DATE}*record*' \) -o -name 'tag_${TARGET_DATE}*.pb.txt' \) 2>/dev/null"

raw_files=$(eval "$find_cmd")
[[ -z $raw_files ]] && { log_error "$data_root 目录下找不到相关的文件！"; exit 1; }
record_list=$(echo "$raw_files" | grep record)
tag_list=$(echo "$raw_files" | grep tag)

# ${bash_dir}/20251220-112907.record.00000.112907
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
[[ -z "$tag_list" ]] && { log_error "$data_root 找不到对应的 tag 文件！"; exit 1; }

for tag_file in $tag_list; do
    content=$(cat "$tag_file")
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
                sorted_candidates=$(echo "$matched_files" | tr ' ' '\n' | sort -n -t'|' -k1,1)
                final_list=""
                declare -A last_before_soc=()
                while read -r line; do
                    [[ -z "$line" ]] && continue
                    f_sec="${line%%|*}"
                    f_path="${line#*|}"

                    if (( f_sec >= end_sec )); then
                        continue
                    fi

                    current_soc="unknown"
                    if [[ "$f_path" == *"soc1"* ]]; then
                        current_soc="soc1"
                    elif [[ "$f_path" == *"soc2"* ]]; then
                        current_soc="soc2"
                    fi

                    if (( f_sec >= start_sec )); then
                        final_list="${final_list} ${f_path}"
                    else
                        last_before_soc[$current_soc]="$f_path"
                    fi
                done <<< "$sorted_candidates"
                merged_last_files=""
                for soc in "${!last_before_soc[@]}"; do
                    merged_last_files="${merged_last_files} ${last_before_soc[$soc]}"
                done
                result="${merged_last_files} ${final_list}"
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
            # t_dir="${t_paths[0]%/*}"
            # t_files=""
            # for f in "${t_paths[@]}"; do t_files+=" ${f##*/}"; done
            found_socs=$(echo "${tag_paths}" | grep -o "soc[12]" | sort -u | xargs)
            echo -e "${GREEN}[$count] $tag_name : $tag_time [$found_socs]${NC}"
            # echo "[目录]: $t_dir"
            # echo "[文件]: ${t_files# }"
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
