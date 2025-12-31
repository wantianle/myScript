#!/bin/bash

set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../utils/logger.sh"

copy_root="${COPY_ROOT:-/home/mini}"
vehicle="${VEHICLE}"
target_date="${DATATIME}"
mode="${REMOTE_MODE:-1}"

work_dir="${copy_root}/${vehicle}/${target_date}"
manifest_file="${work_dir}/task_manifest.list"

[[ ! -f "$manifest_file" ]] && { log_error "清单文件不存在，请先运行 find_record.sh"; exit 1; }

# ================= 1. 展示列表并选择 =================
log_step "待导出任务清单"
printf "%-4s | %-20s | %s\n" "ID" "Time" "Message"
echo "----------------------------------------------------------------------"
while IFS='|' read -r id time msg files; do
    printf "${GREEN}%-4s${NC} | %-20s | %s\n" "$id" "$time" "$msg"
done < "$manifest_file"

echo ""
read -p "请输入要下载的序号 (例如 1,2,5 或输入 0 导出全部): " selection
[[ -z "$selection" ]] && { log_warn "未选择任何任务"; exit 0; }

# ================= 2. 规划任务 =================
declare -a selected_ids
if [[ "$selection" == "0" ]]; then
    selected_ids=($(cut -d'|' -f1 "$manifest_file"))
else
    IFS=',' read -ra selected_ids <<< "$selection"
fi

# ================= 3. 执行同步与下载 =================
human_size() { numfmt --to=iec --format="%.2f" "$1"; }

for sid in "${selected_ids[@]}"; do
    task_line=$(grep "^${sid}|" "$manifest_file")
    IFS='|' read -r id t_time t_name t_files <<< "$task_line"

    # 清洗目录名
    safe_name=$(echo "$t_name" | sed 's/[/\\:*?"<>|]//g' | xargs)
    soc_name="${SOC:-soc1}"
    dest_root="${work_dir}/${safe_name}/${soc_name}"
    mkdir -p "$dest_root"

    log_info "正在处理 [$id]: $safe_name"

    IFS=',' read -ra files_array <<< "$t_files"
    for src in "${files_array[@]}"; do
        dest="${dest_root}/${src##*/}"
        # 简单同步逻辑 (检查大小)
        if [[ -f "$dest" ]]; then
            log_info "跳过已存在文件: ${src##*/}"
        else
            if [[ mode == "remote" ]]; then
                scp -q -o StrictHostKeyChecking=no "$REMOTE_USER@$REMOTE_IP:$src" "$dest"
            else
                cp "$src" "$dest"
            fi
        fi

        # 同步 version.json
        v_src="$(dirname "$src")/version.json"
        if [[ mode == "remote" ]]; then
            rsync -a -o StrictHostKeyChecking=no "$REMOTE_USER@$REMOTE_IP:$v_src" "${dest_root}/version.json" 2>/dev/null || true
        else
            [[ -f "$v_src" ]] && cp "$v_src" "${dest_root}/version.json"
        fi
    done

    # 生成 README (保留原逻辑)
    v_content=$([[ -f "${dest_root}/version.json" ]] && cat "${dest_root}/version.json" || echo "N/A")
    cat << EOF > "${dest_root}/../README.md"
- **tag：** ${t_time}
- **问题描述：** ${t_name}
- **车辆环境：**
\`\`\`json
${v_content}
\`\`\`
EOF
done

log_ok "下载同步任务全部完成！"
