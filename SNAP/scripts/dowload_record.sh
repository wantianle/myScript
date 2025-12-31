#!/bin/bash

set -Eeuo pipefail
LOG_SHOW_TIME=0
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../utils/logger.sh"
# ================= 配置部分 =================
nas_root=$NAS_ROOT
dest_root=$DEST_ROOT
vehicle=$VEHICLE
target_date=$DATATIME
mode=$MODE
remote_user=$REMOTE_USER
remote_ip=$REMOTE_IP
remote_data_root=$REMOTE_DATA_ROOT

# ================= 序号选择逻辑 =================
(( ${#all_tasks[@]} == 0 )) && { log_info "没有查找到符合条件的 record 文件！"; exit 1; }

read -r -p "$(echo -e "\n${YELLOW}确认按 tag 分类复制 record 文件到${dest_root}? (y/Y or quit)${NC}") " input
echo
[[ ! $input =~ ^[Yy]$ ]] && exit 0
echo -e "${YELLOW}找到 $tag_counter 个可导出的 Tag ${NC}"
read -p "请输入要导出的序号 (例如 1,2,5 或输入 0 导出全部): " selection

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
    log_error "未选择任何有效序号！"
    exit 1
fi

human_size() {
    numfmt --to=iec --format="%.2f" "$1"
}

# --- 分行绘制单个 Task 进度条 ---
task_progress() {
    local current_bytes=$1 total_bytes=$2 tag=$3 status=$4
    (( total_bytes <= 0 )) && total_bytes=1
    local percent=$(( current_bytes * 100 / total_bytes ))
    local bar_size=20
    local filled=$(( percent * bar_size / 100 ))
    local empty=$(( bar_size - filled ))
    local bar; bar=$(printf "%${filled}s" | tr ' ' '#')
    local space; space=$(printf "%${empty}s" | tr ' ' '-')
    local label="${YELLOW}[同步中]${END}"
    [[ "$status" == "done" ]] && label="${GREEN}[已完成]${END}"
    printf "\r\e[K%b %-20.20s [%b%b] %3d%% (%s/%s)" \
        "$label" "$tag" "${GREEN}$bar${END}" "${GREEN}$space${END}" "$percent" "$(human_size $current_bytes)" "$(human_size $total_bytes)"
}

# --- 任务预检 ---
log_info "正在预检磁盘空间并规划任务..."
declare -A name_count
declare -a final_tasks
all_t_bytes=0

# task: ${msg}|${result}|${formatted_time}
# msg: xx，xxxx\n : 12/27/2025, 3:24:14 PM
# result: /media/data/data/bag/20251227-151941_soc1/20251227151941.record.00003.152126
# formatted_time: 2025-12-27 15:24:14

# 重命名和计算大小
for task in "${copy_tasks[@]}"; do
    IFS='|' read -r raw_msg file_list tag_time <<< "$task"
    base_name=$(echo "${raw_msg%%:*}" | sed 's/[/\\:*?"<>|]//g' | xargs)

    index=${name_count["$base_name"]:-0}
    final_name="$base_name"
    (( index > 0 )) && final_name="${base_name}${index}"
    ((name_count["$base_name"] = index + 1))

    tasks_bytes=0
    tasks_info=""
    for f in $file_list; do
        if [[ mode == "remote" ]]; then
            f_size=$(ssh_cmd "stat -c %s $f 2>/dev/null || echo 0")
        else
            f_size=$(stat -c %s "$f")
        fi
        tasks_bytes=$((tasks_bytes + f_size))
        tasks_info+="${f}:${f_size} "
        [[ -z $f_size ]] && log_warn "$f 为空文件或无法访问！"
    done
    if [[ -n "$tasks_info" ]]; then
        final_tasks+=("${final_name}|${tasks_bytes}|${tasks_info}|${tag_time}")
        all_t_bytes=$((all_t_bytes + tasks_bytes))
    fi
done
log_info "预检完成，计划同步 $(human_size $all_t_bytes) 数据。"
avail_space=$(df --output=avail -B1 "${dest_root}" | tail -n 1)
if (( "$all_t_bytes" >= "$avail_space" - 1024*32 )); then
    log_error "空间不足！需 $(human_size $all_t_bytes), 可用 $(human_size $avail_space)"
    exit 1
fi

# --- 执行同步 ---
for task in "${final_tasks[@]}"; do
    IFS='|' read -r t_name t_bytes t_info t_time <<< "$task"
    task_info=$(echo "$t_info" | awk '{print $1}')
    soc_name=$(basename "$(dirname "${task_info%%:*}")")
    copy_path="${dest_root}/${vehicle}/${target_date}/${t_name}/${soc_name}"
    mkdir -p "$copy_path"
    declare -A expected_files
    expected_files["version.json"]=1
    for pair in $t_info; do
        expected_files["$(basename "${pair%%:*}")"]=1
    done

    for exist in "$copy_path"/*; do
        [[ -e "$exist" ]] || continue
        filename="${exist##*/}"
        if [[ ! -v expected_files["$filename"] ]]; then
            log_warn "清理多余文件: $filename"
            rm -rf "$exist"
        fi
    done
    unset expected_files

    done_bytes=0
    read -r -a pairs <<< "$t_info"
    for pair in "${pairs[@]}"; do
        src="${pair%%:*}"
        filesize="${pair##*:}"
        dest="$copy_path/${src##*/}"

        if [[ -f "$dest" ]] && (( $(stat -c %s "$dest") == filesize )); then
            done_bytes=$((done_bytes + filesize))
        else

            if [[ mode == "remote" ]]; then
                LC_ALL=C LANG=C scp -q -o ConnectTimeout=3 \
                    -o StrictHostKeyChecking=no \
                    -o UserKnownHostsFile=/dev/null \
                    $remote_user@$remote_ip:$src $dest &
            else
                cp "$src" "$dest" &
            fi
            cp_pid=$!
            while kill -0 $cp_pid 2>/dev/null; do
                written=$(stat -c %s "$dest" 2>/dev/null || echo 0)
                task_progress "$((done_bytes + written))" "$t_bytes" "$t_name" "copying"
                sleep 0.1
            done
            wait $cp_pid
            done_bytes=$((done_bytes + filesize))
        fi

        v_src="$(dirname "$src")/version.json"
        if [[ mode == "remote" ]]; then
            rsync -a "$remote_user@$remote_ip:$v_src" "$copy_path/version.json" 2>/dev/null || true
        else
            [[ -f "$v_src" ]] && cp "$v_src" "$copy_path/version.json"
        fi
    done
    task_progress "$t_bytes" "$t_bytes" "$t_name" "done"
    echo
    # 生成 Readme.md
    tag_root_dir=$(dirname "$copy_path")
    readme_path="${tag_root_dir}/README.md"
    v_json_file="${copy_path}/version.json"
    v_content=""
    if [[ -f "$v_json_file" ]]; then
        v_content=$(cat "$v_json_file")
    fi

    # t_info: "path1:size1 path2:size2 "
    records=""
    for pair in $t_info; do
        record=${pair%%:*}
        records+="${record##*/} "
    done

    cat << EOF > "$readme_path"
- **tag：** ${t_time} ${t_name}
- **问题描述：**
> 填写补充描述
- **预期结果：**
> 填写正确情况
- **实际结果：**
> 填写错误情况
- **车辆软硬件信息：**
\`\`\`yaml
${v_content}
\`\`\`
- **数据路径：**
\`\`\`bash
${nas_root}
\`\`\`
- **数据时刻：**
\`\`\`bash
${records}
\`\`\`
EOF
done
log_info "同步完成，总大小: $(human_size $all_t_bytes)"
