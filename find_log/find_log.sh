#!/bin/bash

# fault:time module err
# find module.log.INFO
# grep 时间段 log
# check core
log_dir=/media/data/data/log
export_dir=/media/issue/iss_$(date +%Y%m%d%H%M%S)
fault_log=$log_dir/supervisor_fault_manage.log

grep -iE "fault|error" $fault_log | grep -v "^$" | tee "$export_dir/fault_manage.log" | awk -F '[ ,:]' '{
    d = $1;
    t = $2$3$4;
    date = substr(d, 1, 8);
    time = substr(t, 2, 9);
    module = $15;
    print sprintf("%s-%s %s", date, time, module)
}' | while read -r datetime module; do
    echo "fault 发生时间: $datetime"
    echo "fault 对应模块: $module"
    found_file=$(find "$log_dir" -type f -name "${module}.log.INFO.*" -print0 | sort -z | \
    awk -v key="$datetime" '
    {
        current_file = $0;
        split(current_file, parts, ".");
        file_time = parts[4];
        if (file_time <= key) {
            result = current_file;
        } else {
            if (result != "") {
                print result;
                exit;
            }
        }
    }
    END {
        if (result != "") print result;
    }')

    if [ -n "$found_file" ]; then
        echo "找到最近的日志文件: $found_file"
        grep -E "($datetime)" "$found_file" | tee -a "$export_dir/${datetime}_${module}.log"
        # 20260317-164322
        std_time="${datetime:9:2}:${datetime:11:2}:${datetime:13:2}"
        start_time=$(date -d "${datetime:0:8} $std_time - 5 seconds" "+%T")
        end_time=$(date -d "${datetime:0:8} $std_time + 5 seconds" "+%T")
        echo "筛选范围: $start_time -- $end_time"
        awk -v start="$start_time" -v end="$end_time" 'start <= $2 && $2 <= end' "$found_file" > "$export_dir/${datetime}_${module}.log"

    else
        echo "未找到对应模块的时间日志文件"
    fi

done
