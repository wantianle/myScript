from typing import List, Optional

from core.models import LibraryEntry, ReplayHistoryEntry


def print_banner() -> None:
    """打印程序主标题。"""
    print("" + "=" * 42)
    print("     witt ( What Is That Tag ? ）v2.0.0")
    print("" + "=" * 42)


def show_playback_library(
    library: List[LibraryEntry],
    vehicle: str,
    target_date: str,
) -> None:
    """打印回放库列表。"""
    print(f"{'ID '} | {vehicle:<9} | {target_date}")
    print("-" * 42)
    for index, entry in enumerate(library, 1):
        print(
            f"{index:<3} ├── \033[3m{entry.time[11:]} \033[1;32m{entry.tag}\033[0m "
        )
        indent = " " * 4
        meta = entry.last_update or {}
        soc1_update = meta.get("soc1", "N/A")
        soc2_update = meta.get("soc2", "N/A")
        print(f"{indent}├── soc1 update: \033[3;33m{soc1_update}\033[0m")
        print(f"{indent}└── soc2 update: \033[3;33m{soc2_update}\033[0m")


def print_text_block(text: str) -> None:
    """按原样打印多行文本块。"""
    if not text:
        return
    print(text, end="" if text.endswith("\n") else "\n")


def show_manual_play_header() -> None:
    """打印手动回播模式标题。"""
    print("" + "=" * 14 + " 手动回播模式 " + "=" * 14)
    print("将 record 文件/目录粘贴或拖入终端 | 'q' 返回")


def show_playback_info(
    tag: str,
    duration: int,
    rate: float = 1.0,
    channels: Optional[List[str]] = None,
) -> None:
    """打印当前回放的概要信息。"""
    print(f"当前回播: \033[1;32m{tag}\033[0m")
    print(f"总时长: \033[1;33m{duration}s\033[0m")
    print(f"播放倍速: \033[1;36mx{rate:g}\033[0m")
    if channels:
        print(f"频道过滤: \033[1;34m{', '.join(channels)}\033[0m")


def show_replay_history(history_entries: List[ReplayHistoryEntry]) -> None:
    """打印回播历史列表。"""
    print("回播历史:")
    print("-" * 108)
    for index, history_entry in enumerate(history_entries, 1):
        range_text = _format_history_range(
            history_entry.start_sec,
            history_entry.end_sec,
        )
        source_mode_text = "{0}/{1}".format(
            history_entry.source_type,
            history_entry.replay_mode,
        )
        channels_text = _format_history_channels(history_entry.channel_filters)
        print(
            "[{0}] 播放时间 {1} | {2} | {3}".format(
                index,
                history_entry.issue_timestamp or history_entry.created_at or "未知时间",
                history_entry.vehicle or "未知车型",
                source_mode_text,
            )
        )
        print(
            "    tag: {0} | range: {1} | rate: x{2:g} | -k: {3}".format(
                history_entry.display_tag or history_entry.selection_label or "未命名回播",
                range_text,
                history_entry.playback_rate,
                channels_text,
            )
        )


def _format_history_range(start_sec: int, end_sec: int) -> str:
    """格式化历史记录中的回播时间范围。"""
    if start_sec <= 0 and end_sec <= 0:
        return "全播"
    if end_sec > 0:
        return f"{start_sec}-{end_sec}s"
    return f"{start_sec}s-全播"


def _format_history_channels(channel_filters: List[str]) -> str:
    """压缩展示频道过滤信息。"""
    if not channel_filters:
        return "无"
    if len(channel_filters) <= 2:
        return ", ".join(channel_filters)
    return "{0}, {1} ...(+{2})".format(
        channel_filters[0],
        channel_filters[1],
        len(channel_filters) - 2,
    )


def print_status(msg: str, level: str = "INFO") -> None:
    """打印终端即时状态，不进入日志文件。"""
    colors = {
        "INFO": "\033[32m",
        "WARN": "\033[33m",
        "ERROR": "\033[31m",
        "RESET": "\033[0m",
    }
    print(f"{colors.get(level, '')}[{level}] {msg}{colors['RESET']}")
