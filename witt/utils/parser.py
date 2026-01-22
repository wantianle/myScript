import math
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

from interface import ui

_RE_TIME = re.compile(
    r"(?:begin|end)_time:\s+(\d{4}[-\s]\d{2}[-\s]\d{2}[-\s]\d{2}:\d{2}:\d{2})"
)
_RE_DURATION = re.compile(r"duration:\s+(\d+\.?\d*)")
_RE_CHANNELS = re.compile(r"(\/mdrive\/[\/\w]+)\s+(\d+)\s+messages")


def parse_record_info(stdout: str) -> Dict[str, Any]:
    """从 cyber_recorder info 的输出中抠出核心数据"""
    raw_time = _RE_TIME.findall(stdout)
    raw_duration = _RE_DURATION.findall(stdout)
    raw_channels = _RE_CHANNELS.findall(stdout)
    begin_time = str_to_time(raw_time[0])
    end_time = str_to_time(raw_time[1])
    duration = math.floor(float(raw_duration[0]))
    channels = [{"name": name, "count": int(count)} for name, count in raw_channels]
    channels.sort(key=lambda x: x["name"])
    return {
        "begin": begin_time,
        "end": end_time,
        "duration": duration,
        "channels": channels,
    }


def sanitize_name(name: str) -> str:
    """清洗目录文件名，去除非法字符"""
    if not name:
        return "unnamed"
    invalid_chars = r'[\\/*?:"<>|！？@#$%^&~`\'"￥+\[\]{}]'
    sanitized = name.strip().replace(" ", "_")
    sanitized = re.sub(invalid_chars, "_", sanitized)
    sanitized = re.sub(r"_+", "_", sanitized)
    return sanitized.strip("._")


def str_to_time(t_str: str) -> datetime:
    """
    统一解析 Cyber 时间字符串为 datetime 对象
    """
    clean_t = (
        f"{t_str[:10]} {t_str[11:]}" if len(t_str) > 10 and t_str[10] == "-" else t_str
    )
    try:
        return datetime.strptime(clean_t, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        ui.print_status(f"无法识别的时间格式: {t_str}", "ERROR")
        raise


def time_to_str(dt: Any) -> str:
    """转回 Cyber 要求的字符串"""
    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    return str(dt)


def parse_manifest(manifest_path: Path) -> List[Dict[str, Any]]:
    """解析 find_record.sh 生成的 manifest.list"""
    # time|tag|paths
    lines = [
        line.strip()
        for line in manifest_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    tasks = []
    for line in lines:
        parts = line.split("|")
        tasks.append(
            {
                "time": parts[0],
                "name": sanitize_name(parts[1]),
                "paths": parts[2].split(),
            }
        )
    tasks.sort(key=lambda x: x["time"])
    for i, task in enumerate(tasks, start=1):
        task["id"] = f"{i:02d}"
    return tasks


def parse_range_logic(range_in: str) -> tuple:
    """
    专门处理播放时间范围字符串，确保永远返回两个整数
    """
    if not range_in:
        return 0, 0
    try:
        nums = re.findall(r"\d+", range_in)
        if len(nums) >= 2:
            return int(nums[0]), int(nums[1])
        elif len(nums) == 1:
            return int(nums[0]), 0
    except (ValueError, TypeError):
        pass
    return 0, 0


def sort_records(file_list: list) -> list:
    """
    根据 Cyber Record 的序号进行全局排序
    排序规则：先按序号排，序号相同按文件名排（处理 soc1/soc2 同序号情况）
    文件名示例: 20260110125227.record.00005.125739
    """

    def get_index(path) -> int:
        match = re.search(r"\.record\.(\d+)", path.name)
        return int(match.group(1)) if match else 0

    return sorted(file_list, key=lambda x: (get_index(x), x.name))
