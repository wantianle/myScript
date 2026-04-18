import re
import urllib.parse
from pathlib import Path
from typing import List, Optional

from core.issue_draft import ReplayIssueMarker
from core.models import LibraryEntry, ReplayHistoryEntry, ReplayRecord, TaskEntry
from interface import prompter, ui
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
        raw_choice = prompter.prompt_text(
            "选择播放序号 (回车取消)",
            history_name="playback_entry",
            completer_words=[str(index) for index in range(1, len(filtered_library) + 1)],
        )
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

        completer_words = [str(index) for index in range(1, len(socs) + 1)] + socs
        if len(socs) > 1:
            completer_words.append(str(len(socs) + 1))
            completer_words.append("All")
        choice = prompter.prompt_text(
            "选择要播放的 SOC",
            "1",
            history_name="soc_selection",
            completer_words=completer_words,
        ) or "1"
        normalized_choice = choice.lower()
        if choice.isdigit():
            soc_index = int(choice)
            if 1 <= soc_index <= len(socs):
                return tag_entry.socs[socs[soc_index - 1]]
            if len(socs) > 1 and soc_index == len(socs) + 1:
                target_records = []
                for soc_name in socs:
                    target_records.extend(tag_entry.socs[soc_name])
                return target_records
        for soc_name in socs:
            if normalized_choice == soc_name.lower():
                return tag_entry.socs[soc_name]
        if len(socs) > 1 and normalized_choice == "all":
            target_records = []
            for soc_name in socs:
                target_records.extend(tag_entry.socs[soc_name])
            return target_records
        ui.print_status("输入无效，请重新选择", "WARN")


def select_source_task_entry(
    task_entries: List[TaskEntry],
    find_record_output: str = "",
) -> Optional[TaskEntry]:
    """从查询结果列表中选择一个用于全量回放的 Tag。"""
    if not task_entries:
        return None
    while True:
        ui.print_text_block(find_record_output)
        raw_choice = prompter.prompt_text(
            "选择要回放的 Tag 序号 (回车返回)",
            history_name="source_task_entry",
            completer_words=[str(index) for index in range(1, len(task_entries) + 1)],
        )
        if not raw_choice:
            return None
        if raw_choice.isdigit():
            selected_index = int(raw_choice)
            if 1 <= selected_index <= len(task_entries):
                return task_entries[selected_index - 1]
        ui.print_status("输入无效，请重新选择", "WARN")


def select_replay_history_index(
    history_entries: List[ReplayHistoryEntry],
) -> Optional[int]:
    """在浏览历史后输入序号选择一条回播记录。"""
    if not history_entries:
        ui.print_status("当前没有可用的回播历史", "WARN")
        return None
    while True:
        raw_choice = prompter.prompt_text(
            "输入要回播的历史序号 (0 清空历史 | 回车返回)",
            history_name="history_selection",
            completer_words=["0"] + [
                str(index) for index in range(1, len(history_entries) + 1)
            ],
        )
        if not raw_choice:
            return None
        if raw_choice.isdigit():
            selected_index = int(raw_choice)
            if selected_index == 0:
                return 0
            if 1 <= selected_index <= len(history_entries):
                return selected_index
        ui.print_status("输入无效，请重新选择", "WARN")


def get_playback_range() -> tuple:
    """读取并解析回放时间范围输入。"""
    range_input = prompter.prompt_text(
        "调整播放时间 (改变起点 5 | 限制范围 5-10 | 回车全播)",
        history_name="playback_range",
    )
    return parser.parse_range_logic(range_input)


def get_playback_rate() -> float:
    """读取播放倍速，范围限制在 0.1 到 10 之间。"""
    while True:
        rate_input = prompter.prompt_text(
            "播放倍速 (0.1-10 | 回车 1.0)",
            "1.0",
            history_name="playback_rate",
            completer_words=["0.5", "1.0", "1.5", "2.0"],
        ).strip()
        if not rate_input:
            return 1.0
        try:
            playback_rate = float(rate_input)
        except ValueError:
            ui.print_status("请输入合法倍速", "WARN")
            continue
        if 0.1 <= playback_rate <= 10:
            return playback_rate
        ui.print_status("播放倍速需在 0.1 到 10 之间", "WARN")


def get_issue_marker() -> Optional[ReplayIssueMarker]:
    """回播结束后读取问题时间点和备注。"""
    if not prompter.get_confirm_input("是否记录问题时间点标记？"):
        return None
    return ReplayIssueMarker(
        playback_start_sec=_get_issue_start_sec(),
        issue_description=_get_issue_description(),
    )


def _get_issue_start_sec() -> int:
    """读取问题时间点秒数，用于覆盖 issue 草稿中的 range(-s)。"""
    while True:
        raw_value = prompter.prompt_text(
            "问题时间点秒数(-s，例 37)",
            history_name="issue_start_sec",
        )
        if raw_value.isdigit():
            return int(raw_value)
        ui.print_status("请输入非负整数秒数", "WARN")


def _get_issue_description() -> str:
    """读取问题现象备注。"""
    while True:
        issue_description = prompter.prompt_text(
            "简短备注",
            history_name="issue_description",
        )
        if issue_description:
            return issue_description
        ui.print_status("备注不能为空", "WARN")


def get_issue_data_path_text(target_date: str, vehicle: str) -> str:
    """在自动推断失败时手动补录准确 NAS 路径。"""
    expected_prefix = "/media/nas/00.raw/{0}/{1}".format(target_date, vehicle)
    ui.print_status("无法自动推断准确 NAS 路径，请手动补录 issue 草稿中的准确 NAS 路径", "WARN")
    ui.print_status("路径需以 {0} 开头".format(expected_prefix))
    issue_paths = []
    while True:
        raw_line = prompter.prompt_text(
            "NAS路径(空行结束)",
            history_name="issue_nas_path",
            path_completion=True,
        )
        if not raw_line:
            if issue_paths:
                return "\n".join(issue_paths)
            ui.print_status("至少输入一条准确 NAS 路径，或按 Ctrl+C 取消", "WARN")
            continue
        if not raw_line.startswith(expected_prefix):
            ui.print_status("路径必须以 {0} 开头".format(expected_prefix), "WARN")
            continue
        issue_paths.append(raw_line)


def get_manual_replay_paths() -> List[Path]:
    """获取手动回放模式下用户提供的文件路径列表。"""
    ui.show_manual_play_header()
    return get_dragged_input()


def get_dragged_input() -> List[Path]:
    """
    读取拖拽进终端的 record 文件或目录并返回排序后的文件列表。
    """
    raw_input = prompter.prompt_text(
        "拖拽或粘贴 record 文件/目录 (q 返回)",
        history_name="manual_paths",
        path_completion=True,
    )
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
