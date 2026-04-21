import math
import re
from datetime import datetime
from pathlib import Path
from typing import List, Sequence, Tuple, Union

from core.models import ChannelInfo, RecordInfo

_RE_TIME = re.compile(
    r"(?:begin|end)_time:\s+(\d{4}[-\s]\d{2}[-\s]\d{2}[-\s]\d{2}:\d{2}:\d{2})"
)
_RE_DURATION = re.compile(r"duration:\s+(\d+\.?\d*)")
_RE_CHANNELS = re.compile(r"(\/mdrive\/[\/\w]+)\s+(\d+)\s+messages")


def parse_record_info(stdout: str) -> RecordInfo:
    """从 cyber_recorder info 的输出中抠出核心数据"""
    raw_time = _RE_TIME.findall(stdout)
    raw_duration = _RE_DURATION.findall(stdout)
    raw_channels = _RE_CHANNELS.findall(stdout)
    if len(raw_time) < 2 or not raw_duration:
        raise ValueError("cyber_recorder info 输出不完整")
    begin_time = str_to_time(raw_time[0])
    end_time = str_to_time(raw_time[1])
    duration = math.floor(float(raw_duration[0]))
    channels = [
        ChannelInfo(name=name, count=int(count))
        for name, count in raw_channels
    ]
    return RecordInfo.from_components(
        begin=begin_time,
        end=end_time,
        duration=duration,
        channels=channels,
    )


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
    """统一解析 Cyber 时间字符串为 datetime 对象"""
    clean_t = str(t_str).strip()
    if len(clean_t) > 10 and clean_t[10] in ("-", "T"):
        clean_t = "{0} {1}".format(clean_t[:10], clean_t[11:])
    try:
        return datetime.strptime(clean_t, "%Y-%m-%d %H:%M:%S")
    except ValueError as e:
        raise ValueError("无法识别的时间格式: {0}".format(t_str)) from e


def time_to_str(dt: Union[datetime, str]) -> str:
    """将 datetime 或字符串转换为 Cyber 需要的时间字符串。"""
    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    return str(dt)


def parse_range_logic(range_in: str) -> Tuple[int, int]:
    """解析播放时间范围字符串并返回起止秒数。"""
    if not range_in:
        return 0, 0
    nums = re.findall(r"\d+", range_in)
    if len(nums) >= 2:
        return int(nums[0]), int(nums[1])
    if len(nums) == 1:
        return int(nums[0]), 0
    return 0, 0


def sort_records(file_list: Sequence[Path]) -> List[Path]:
    """
    根据 Cyber Record 的序号进行全局排序
    排序规则：先按序号排，序号相同按文件名排（处理 soc1/soc2 同序号情况）
    文件名示例: 20260110125227.record.00005.125739
    """

    def get_index(path: Path) -> int:
        match = re.search(r"\.record\.(\d+)", path.name)
        return int(match.group(1)) if match else 0

    return sorted(file_list, key=lambda path: (get_index(path), path.name))
