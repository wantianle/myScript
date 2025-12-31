#!/bin/bash

set -Eeuo pipefail
# ================= 配置部分 =================
# 日志颜色
NC=$'\e[0m'
RED=$'\e[0;31m'
GREEN=$'\e[0;32m'
YELLOW=$'\e[0;33m'
BLUE=$'\e[0;34m'
if [ ! -t 1 ]; then
    RED= GREEN= YELLOW= BLUE= NC=
fi
log_info() {
    printf "${BLUE}[INFO] %s${NC}\n" "$*"
}
log_ok() {
    printf "${GREEN}[OK] %s${NC}\n" "$*"
}
log_warn() {
    printf "${YELLOW}[WARN] %s${NC}\n" "$*"
}
log_error() {
    printf "${RED}[ERROR] %s${NC}\n" "$*"
}
# 初始化变量
copy_root="/home/mini"
mount_root="/media/nas"
vehicle=""
target_date=""
target_path=""
lookback=2
target_soc="soc1"
# 远程模式变量
remote_mode=0
remote_user="nvidia"
remote_ip="192.168.10.2"
remote_data_root="/media/data/data/bag"
# 帮助信息
show_help() {
    cat << EOF
${BLUE}Record 数据提取与分类工具${NC}
依据 Tag 文件自动检索并导出相关的 record 数据片段。

${YELLOW}用法:${NC}
  $0 -t <date> [-v <vehicle>] [-p <path>] [-m <lookback>] [-s <soc>] [-d <copy_path>] [-h]

${YELLOW}参数说明:${NC}
  ${GREEN}-t <date>${NC}      ${RED}[必填]${NC} 目标日期，格式为 YYYYMMDD (如: 20251224)。
  ${GREEN}-v <vehicle>${NC}   车辆 ID (如: XZB600012)。用于自动拼接 NAS 路径。
                  若未指定 -p，则此项为必填。
  ${GREEN}-p <path>${NC}      手动指定本地扫描路径。若指定此项，将跳过 NAS 检索。
  ${GREEN}-m <lookback>${NC}  回溯片段数 (默认: 2)。指在 Tag 时间点之前检索多少个 record 片段。
  ${GREEN}-s <soc>${NC}       目标 SOC 类型 (默认: soc1)。用于过滤文件名中的控制器标识。
  ${GREEN}-d <copy_path>${NC} 指定导出路径 (默认: /home/mini)。
  ${GREEN}-h${NC}             显示此帮助信息。

${YELLOW}输出说明:${NC}
  1. 自动在 ~/Documents 生成检索清单 (*_record.txt) 和 Tag 清单 (*_tag.txt)。
  2. 支持交互式选择特定序号的 Tag 进行本地导出 record 文件。
  3. 自动计算磁盘空间、提供进度条、支持断点续传、支持增量同步。
  4. 导出路径结构: ${copy_root}/<date>/<tag_name>/<soc_type>/
  5. tag的命名规则为: tag*<date>*.txt 否则无法识别。

${YELLOW}使用示例:${NC}
  # 场景 1: 检索 NAS 上某车特定日期(可精确到小时)的 soc1 数据
  $0 -v XZB600012 -t 20251224
  $0 -v XZB600012 -t 2025122414

  # 场景 2: 检索本地数据任意父路径，并回溯 5 个片段
  $0 -p /media/mini -t 20251224 -m 5
  $0 -p /media/mini/data/data/bag -t 20251224 -m 5

  # 场景 3: 检索 SOC2 的数据，导出到 /media/test_data 目录
  $0 -p /media/mini -t 20251224 -s soc2 -d /media/test_data

${YELLOW}注意:${NC}
  远程模式建议先执行: ${GREEN}ssh-copy-id $remote_user@$remote_ip${NC} 以实现免密登录。

EOF
    exit 0
}

while getopts "v:t:p:m:s:d:rh" opt; do
    case $opt in
        v) vehicle="$OPTARG" ;;
        t) target_date="$OPTARG" ;;
        p) target_path="$OPTARG" ;;
        m) lookback="$OPTARG" ;;
        s) target_soc="$OPTARG" ;;
        d) copy_root="$OPTARG" ;;
        r) remote_mode=1 ;;
        h) show_help ;;
        *) echo "未知参数。使用 -h 查看详细说明。"; exit 1 ;;
    esac
done

if [[ -z "$target_date" ]]; then
    log_error "缺少日期参数！"
    exit 1
fi
# 路径文件保存目录
if [[ -d "$HOME/Documents" ]]; then
    output_dir="$HOME/Documents"
elif [[ -d "$HOME/文档" ]]; then
    output_dir="$HOME/文档"
else
    output_dir="$HOME"
    log_warn "未找到文档 Documents 目录，保存至 $HOME"
fi
record_output_file="${output_dir}/${target_date}_${vehicle:-test}_record.txt"
tag_output_file="${output_dir}/${target_date}_${vehicle:-test}_tag.txt"
> "$record_output_file"
> "$tag_output_file"
# ================= 确定查询模式 =================
if (( remote_mode )); then
    base_dir="${target_path:-$remote_data_root}"
    log_info "远程模式: $remote_user@$remote_ip:$base_dir"
    ssh_cmd() {
        LC_ALL=C LANG=C ssh -o ConnectTimeout=3 \
            -o StrictHostKeyChecking=no \
            -o UserKnownHostsFile=/dev/null \
            -o LogLevel=ERROR \
            "$remote_user@$remote_ip" "LC_ALL=C $@"
    }
elif [[ -n "$target_path" ]]; then
    base_dir="${target_path%/}"
    log_info "本地路径模式: $base_dir"
else
    [[ -z "$vehicle" ]] && { log_error "NAS 模式缺少车辆 ID (-v)"; exit 1; }
    base_dir="${mount_root}/04.mdrive3/01.road_test/${vehicle}/${target_date:0:4}/${target_date}"
    log_info "NAS 模式: $base_dir"
fi

# ================= 建立 Record 索引 (精确到秒) =================
declare -A records
shopt -s nullglob
find_cmd="find \"$base_dir\" -type f \( \( -path '*${target_soc}*' -name '${target_date}*record*' \) -o -name 'tag_${target_date}*.pb.txt' \) 2>/dev/null"

if (( remote_mode )); then
    raw_files=$(ssh_cmd "$find_cmd") || { log_error "无法连接车机或找不到对应record 文件！"; exit 1; }
else
    raw_files=$(eval "$find_cmd")
fi
record_list=$(echo "$raw_files" | grep "record")
tag_list=$(echo "$raw_files" | grep "tag")

# ${bash_dir}/20251220-112907.record.00000.112907
[[ -z "$record_list" ]] && { log_error "$base_dir 目录下找不到 record 文件！"; exit 1; }
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
# log_info "Find record files Successful! Finding records before tag time..."

# ================= 处理 Tag 文件 =================
all_tasks=()
tag_counter=0
[[ -z "$tag_list" ]] && { log_error "$base_dir 找不到对应的 tag 文件！"; exit 1; }
for tag_file in $tag_list; do
    if (( remote_mode )); then
        content=$(ssh_cmd "cat $tag_file")
    else
        content=$(cat "$tag_file")
    fi
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
                if (( $f_sec <= $msg_seconds )); then
                    matched_files="${matched_files} ${f_sec}|${f_path}"
                fi
            done

            if [[ -n "$matched_files" ]]; then
                result=$(echo "$matched_files" | tr ' ' '\n' | sort -n | tail -n "$lookback" | cut -d'|' -f2 | tr '\n' ' ')
            else
                is_error=1
            fi

            # 输出部分
            if (( "$is_error" == 1 )); then
                log_warn "$msg ==> 找不到对应 record 文件，请检查是否存在或增加回溯片段数！"
            else
                tag_counter=$((tag_counter + 1))
                log_ok "[$tag_counter] $msg"
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

                all_tasks+=("${msg}|${result}")
            fi

            echo ""
            { echo "$msg"; echo "$result"; echo ""; } >> "$record_output_file"
            echo "$msg" >> "$tag_output_file"
        fi
    done <<< "$content"
    # done < "$tag_file"
done
log_ok "保存 record 路径文件: $record_output_file"
log_ok "保存 tag 文件: $tag_output_file"

# ================= 序号选择逻辑 =================
(( ${#all_tasks[@]} == 0 )) && { log_info "没有查找到符合条件的 record 文件！"; exit 1; }

read -n 1 -r -p "$(echo -e "\n${YELLOW}确认按 tag 分类复制 record 文件到${copy_root}/${target_date}? (y/Y or quit)${NC}") " input
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
    local YELLOW="\e[33m"
    local GREEN="\e[32m"
    local END="\e[0m"
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
# 重命名和计算大小
for task in "${copy_tasks[@]}"; do
    raw_msg="${task%%|*}"
    file_list="${task#*|}"
    base_name=$(echo "${raw_msg%%:*}" | sed 's/[/\\:*?"<>|]//g' | xargs)

    index=${name_count["$base_name"]:-0}
    final_name="$base_name"
    (( index > 0 )) && final_name="${base_name}${index}"
    ((name_count["$base_name"] = index + 1))

    tasks_bytes=0
    tasks_info=""
    for f in $file_list; do
        if (( remote_mode )); then
            f_size=$(ssh_cmd "stat -c %s $f 2>/dev/null || echo 0")
        else
            f_size=$(stat -c %s "$f")
        fi
        tasks_bytes=$((tasks_bytes + f_size))
        tasks_info+="${f}:${f_size} "
        [[ -z $f_size ]] && log_warn "$f 为空文件或无法访问！"
    done
    if [[ -n "$tasks_info" ]]; then
        final_tasks+=("${final_name}|${tasks_bytes}|${tasks_info}")
        all_t_bytes=$((all_t_bytes + tasks_bytes))
    fi
done
log_info "预检完成，计划同步 $(human_size $all_t_bytes) 数据。"
avail_space=$(df --output=avail -B1 "${copy_root}" | tail -n 1)
if (( "$all_t_bytes" >= "$avail_space" - 1024*32 )); then
    log_error "空间不足！需 $(human_size $all_t_bytes), 可用 $(human_size $avail_space)"
    exit 1
fi

# --- 执行同步 ---
for task in "${final_tasks[@]}"; do
    IFS='|' read -r t_name t_bytes t_info <<< "$task"
    task_info=$(echo "$t_info" | awk '{print $1}')
    soc_name=$(basename "$(dirname "${task_info%%:*}")")
    copy_path="${copy_root}/${target_date}/${t_name}/${soc_name}"
    mkdir -p "$copy_path"

    # 增量清理 (Sync)
    # expected_list=$(
    #     {
    #         echo "version.json"
    #         for pair in $t_info; do echo "${pair%%:*}" | xargs basename; done
    #     } | sort
    # )
    # for exist in "$copy_path"/*; do
    #     [[ -e "$exist" ]] || continue
    #     filename="${exist##*/}"
    #     if ! grep -qx "$filename" <<< "$expected_list"; then
    #         echo "清理多余文件: $filename"
    #         rm -rf "$exist"
    #     fi
    # done

    # 性能优化
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

            if (( remote_mode )); then
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
        if (( remote_mode )); then
            rsync -a "$remote_user@$remote_ip:$v_src" "$copy_path/version.json" 2>/dev/null || true
        else
            [[ -f "$v_src" ]] && cp "$v_src" "$copy_path/version.json"
        fi
    done
    task_progress "$t_bytes" "$t_bytes" "$t_name" "done"
    echo
done
log_ok "同步完成，总大小: $(human_size $all_t_bytes)"
