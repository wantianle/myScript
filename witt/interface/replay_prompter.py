import re
import select
import sys
import urllib.parse
from pathlib import Path
from typing import List, Optional

from core.models import LibraryEntry, ReplayRecord, TaskEntry
from interface import ui
from utils import parser


def select_playback_entry(
    library: List[LibraryEntry],
    vehicle: str,
    target_date: str,
) -> Optional[LibraryEntry]:
    """从过滤后的回放库中选择一个回放条目。"""
    filtered_library = [
        entry
        for entry in library
        if entry.date == target_date and entry.vehicle == vehicle
    ]
    if not filtered_library:
        ui.print_status("当前目录下没有符合条件的回播数据", "WARN")
        return None
    while True:
        ui.show_playback_library(filtered_library, vehicle, target_date)
        raw_choice = input("\n选择播放序号 (回车取消): ").strip()
        if not raw_choice:
            return None
        if raw_choice.isdigit():
            index = int(raw_choice)
            if 1 <= index <= len(filtered_library):
                return filtered_library[index - 1]
        ui.print_status("输入无效，请重新选择", "WARN")


def select_replay_records(tag_entry: LibraryEntry) -> List[ReplayRecord]:
    """从单个回放条目中选择要播放的 SOC 记录。"""
    socs = sorted(list(tag_entry.socs.keys()))
    if not socs:
        ui.print_status("当前回播条目没有可用的 SOC 数据", "WARN")
        return []
    while True:
        for i, soc_name in enumerate(socs, 1):
            print(f"  [{i}] {soc_name}")
        if len(socs) > 1:
            print(f"  [{len(socs) + 1}] All")

        choice = input("选择要播放的 SOC (默认 1): ").strip() or "1"
        if choice.isdigit():
            soc_index = int(choice)
            if 1 <= soc_index <= len(socs):
                return tag_entry.socs[socs[soc_index - 1]]
            if len(socs) > 1 and soc_index == len(socs) + 1:
                target_records = []
                for soc_name in socs:
                    target_records.extend(tag_entry.socs[soc_name])
                return target_records
        ui.print_status("输入无效，请重新选择", "WARN")


def select_source_task_entry(task_entries: List[TaskEntry]) -> Optional[TaskEntry]:
    """从查询结果列表中选择一个用于全量回放的 Tag。"""
    if not task_entries:
        return None
    while True:
        print("-" * 48)
        for index, task_entry in enumerate(task_entries, 1):
            available_socs = [
                soc_name
                for soc_name, path_list in sorted(task_entry.soc_paths.items())
                if path_list
            ]
            soc_summary = " ".join(available_socs) if available_socs else "no_soc"
            print(f"[{index}] {task_entry.name} : {task_entry.time} [{soc_summary}]")
        print("-" * 48)
        raw_choice = input("选择要回放的 Tag 序号 (回车返回): ").strip()
        if not raw_choice:
            return None
        if raw_choice.isdigit():
            selected_index = int(raw_choice)
            if 1 <= selected_index <= len(task_entries):
                return task_entries[selected_index - 1]
        ui.print_status("输入无效，请重新选择", "WARN")


def get_playback_range() -> tuple:
    """读取并解析回放时间范围输入。"""
    range_input = input(
        "调整播放时间 (改变起点 5 | 限制范围 5-10 | 回车全播): "
    ).strip()
    return parser.parse_range_logic(range_input)


def get_manual_replay_paths() -> List[Path]:
    """获取手动回放模式下用户提供的文件路径列表。"""
    ui.show_manual_play_header()
    return get_dragged_input()


def get_dragged_input() -> List[Path]:
    """
    读取拖拽进终端的 record 文件或目录并返回排序后的文件列表。
    """
    lines = [sys.stdin.readline()]
    while select.select([sys.stdin], [], [], 0.1)[0]:
        line = sys.stdin.readline()
        if line:
            lines.append(line)
        else:
            break
    raw_input = "".join(lines).strip()
    if raw_input.lower() == "q":
        return []
    if not raw_input:
        return []
    normalized = raw_input.replace("\r", " ").replace("\n", " ")
    if "file://" in normalized:
        parts = [p.strip() for p in normalized.split("file://") if p.strip()]
        paths = [urllib.parse.unquote(p) for p in parts]
    else:
        paths = re.findall(r'(?:[^\s"\']|["\'][^"\']*["\'])+', normalized)
        paths = [p.strip("'\"") for p in paths]

    record_files = []
    for path_text in paths:
        path_obj = Path(path_text)
        if not path_obj.exists():
            continue
        if path_obj.is_dir():
            for candidate_file in path_obj.rglob("*"):
                if candidate_file.is_file() and ".record" in candidate_file.name:
                    record_files.append(candidate_file)
        elif ".record" in path_obj.name:
            record_files.append(path_obj)
    sorted_paths = parser.sort_records(list(set(record_files)))
    if not sorted_paths:
        ui.print_status("无效路径", "ERROR")
    return sorted_paths
