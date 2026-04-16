from typing import List, Optional

from core.models import LibraryEntry


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
    channels: Optional[List[str]] = None,
) -> None:
    """打印当前回放的概要信息。"""
    print(f"当前回播: \033[1;32m{tag}\033[0m")
    print(f"总时长: \033[1;33m{duration}s\033[0m")
    if channels:
        print(f"频道过滤: \033[1;34m{', '.join(channels)}\033[0m")


def print_status(msg: str, level: str = "INFO") -> None:
    """打印终端即时状态，不进入日志文件。"""
    colors = {
        "INFO": "\033[32m",
        "WARN": "\033[33m",
        "ERROR": "\033[31m",
        "RESET": "\033[0m",
    }
    print(f"{colors.get(level, '')}[{level}] {msg}{colors['RESET']}")
