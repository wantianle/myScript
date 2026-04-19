import re
import urllib.parse
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, TypeVar

from core.issue_draft import ReplayIssueMarker
from core.models import LibraryEntry, ReplayHistoryEntry, ReplayRecord, TaskEntry
from interface import prompter, ui
from utils import parser

SelectableItem = TypeVar("SelectableItem")
SelectionResult = TypeVar("SelectionResult")


def _build_soc_selection_items(
    soc_records: Dict[str, List[ReplayRecord]],
) -> Tuple[List[Tuple[str, str, List[ReplayRecord]]], str]:
    """构造 SOC 选择项和默认值。"""
    soc_names = sorted(list(soc_records.keys()))
    if not soc_names:
        return [], ""
    standard_soc_names = ["soc1", "soc2"]
    if all(soc_name in standard_soc_names for soc_name in soc_names):
        selection_items = []
        if "soc1" in soc_records:
            selection_items.append(("1", "soc1", soc_records["soc1"]))
        if "soc2" in soc_records:
            selection_items.append(("2", "soc2", soc_records["soc2"]))
        if "soc1" in soc_records and "soc2" in soc_records:
            all_records = list(soc_records["soc1"]) + list(soc_records["soc2"])
            selection_items.append(("3", "All", all_records))
            return selection_items, "3"
        if "soc1" in soc_records:
            return selection_items, "1"
        return selection_items, "2"

    selection_items = []
    for index, soc_name in enumerate(soc_names, 1):
        selection_items.append((str(index), soc_name, soc_records[soc_name]))
    if len(soc_names) > 1:
        all_records = []
        for soc_name in soc_names:
            all_records.extend(soc_records[soc_name])
        selection_items.append((str(len(soc_names) + 1), "All", all_records))
    return selection_items, "1"


def _filter_playback_entries(
    library: List[LibraryEntry],
    keyword: str,
) -> List[LibraryEntry]:
    """按关键字过滤回放库条目。"""
    return [
        entry
        for entry in library
        if prompter.matches_search_keyword(
            keyword,
            [
                entry.tag,
                entry.time,
                entry.vehicle,
                entry.date,
                " ".join(sorted(entry.socs.keys())),
            ],
        )
    ]


def _filter_task_entries(
    task_entries: List[TaskEntry],
    keyword: str,
) -> List[TaskEntry]:
    """按关键字过滤查询结果条目。"""
    return [
        task_entry
        for task_entry in task_entries
        if prompter.matches_search_keyword(
            keyword,
            [
                task_entry.id,
                task_entry.time,
                task_entry.name,
                len(task_entry.paths),
            ],
        )
    ]


def _filter_history_entries(
    history_entries: List[ReplayHistoryEntry],
    keyword: str,
) -> List[ReplayHistoryEntry]:
    """按关键字过滤历史回播条目。"""
    return [
        history_entry
        for history_entry in history_entries
        if prompter.matches_search_keyword(
            keyword,
            [
                history_entry.created_at,
                history_entry.issue_timestamp,
                history_entry.vehicle,
                history_entry.selection_label,
                history_entry.display_tag,
                history_entry.source_type,
                history_entry.replay_mode,
            ],
        )
    ]


def _select_filtered_value(
    all_items: List[SelectableItem],
    render_items: Callable[[List[SelectableItem], str, int], None],
    filter_items: Callable[[List[SelectableItem], str], List[SelectableItem]],
    prompt: str,
    history_name: str,
    selection_resolver: Callable[[List[SelectableItem], int], SelectionResult],
    render_when_unfiltered: bool = True,
    empty_warn_message: str = "当前筛选结果为空，请调整关键字或输入 / 清空筛选",
    extra_choices: Optional[Dict[str, SelectionResult]] = None,
) -> Optional[SelectionResult]:
    """执行带关键字筛选的单选循环。"""
    current_items = list(all_items)
    search_keyword = ""
    while True:
        if render_when_unfiltered or search_keyword:
            render_items(current_items, search_keyword, len(all_items))
        completer_words = [str(index) for index in range(1, len(current_items) + 1)]
        if extra_choices:
            completer_words = list(extra_choices.keys()) + completer_words
        raw_choice = prompter.prompt_text(
            prompt,
            history_name=history_name,
            completer_words=completer_words,
        )
        if not raw_choice:
            return None
        filter_keyword = prompter.resolve_filter_keyword(raw_choice)
        if filter_keyword is not None:
            next_items = filter_items(all_items, filter_keyword)
            search_keyword = filter_keyword
            current_items = next_items if filter_keyword else list(all_items)
            continue
        if extra_choices and raw_choice in extra_choices:
            return extra_choices[raw_choice]
        if not current_items:
            ui.print_status(empty_warn_message, "WARN")
            continue
        if raw_choice.isdigit():
            selected_index = int(raw_choice)
            if 1 <= selected_index <= len(current_items):
                return selection_resolver(current_items, selected_index)
        ui.print_status("输入无效，请重新选择", "WARN")


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
    return _select_filtered_value(
        filtered_library,
        lambda current_library, search_keyword, total_count: ui.show_playback_library(
            current_library,
            vehicle,
            target_date,
            search_keyword=search_keyword,
            total_count=total_count,
        ),
        _filter_playback_entries,
        "选择播放序号 (/关键字筛选 | / 清空筛选 | 回车取消)",
        "playback_entry",
        lambda current_library, selected_index: current_library[selected_index - 1],
    )


def select_replay_records(tag_entry: LibraryEntry) -> List[ReplayRecord]:
    """从单个回放条目中选择要播放的 SOC 记录。"""
    selection_items, default_choice = _build_soc_selection_items(tag_entry.socs)
    if not selection_items:
        ui.print_status("当前回播条目没有可用的 SOC 数据", "WARN")
        return []
    option_labels = [option_label for _, option_label, _ in selection_items]
    default_index = int(default_choice) if default_choice.isdigit() else 0
    while True:
        ui.show_option_choices(
            "SOC 选择",
            "选择要播放的 SOC",
            option_labels,
            default_index=default_index,
            summary="当前 Tag: {0}".format(tag_entry.tag),
        )
        completer_words = []
        for option_value, option_label, _ in selection_items:
            completer_words.append(option_value)
            completer_words.append(option_label)
        choice = prompter.prompt_text(
            "选择要播放的 SOC",
            default_choice,
            history_name="soc_selection",
            completer_words=completer_words,
        ) or default_choice
        normalized_choice = choice.lower()
        for option_value, option_label, option_records in selection_items:
            if choice == option_value or normalized_choice == option_label.lower():
                return option_records
        ui.print_status("输入无效，请重新选择", "WARN")


def select_source_task_entry(
    task_entries: List[TaskEntry],
) -> Optional[TaskEntry]:
    """从查询结果列表中选择一个用于全量回放的 Tag。"""
    if not task_entries:
        return None
    return _select_filtered_value(
        task_entries,
        lambda current_task_entries, search_keyword, total_count: ui.show_source_task_entries(
            current_task_entries,
            search_keyword=search_keyword,
            total_count=total_count,
        ),
        _filter_task_entries,
        "选择要回放的 Tag 序号 (/关键字筛选 | / 清空筛选 | 回车返回)",
        "source_task_entry",
        lambda current_task_entries, selected_index: current_task_entries[selected_index - 1],
    )


def select_replay_history_index(
    history_entries: List[ReplayHistoryEntry],
) -> Optional[int]:
    """在浏览历史后输入序号选择一条回播记录。"""
    if not history_entries:
        ui.print_status("当前没有可用的回播历史", "WARN")
        return None
    return _select_filtered_value(
        history_entries,
        lambda current_history_entries, search_keyword, total_count: ui.show_filtered_replay_history(
            current_history_entries,
            search_keyword=search_keyword,
            total_count=total_count,
        ),
        _filter_history_entries,
        "输入要回播的历史序号 (0 清空历史 | /关键字筛选 | 回车返回)",
        "history_selection",
        lambda current_history_entries, selected_index: history_entries.index(
            current_history_entries[selected_index - 1]
        ) + 1,
        render_when_unfiltered=False,
        extra_choices={"0": 0},
    )


def get_playback_range() -> tuple:
    """读取并解析回放时间范围输入。"""
    ui.show_replay_section(
        "播放范围配置",
        "调整起点或限制回播时间范围",
        "输入 5 表示改变起点，输入 5-10 表示限制范围，回车全播",
    )
    range_input = prompter.prompt_text(
        "调整播放时间",
        history_name="playback_range",
    )
    return parser.parse_range_logic(range_input)


def get_playback_rate() -> float:
    """读取播放倍速，范围限制在 0.1 到 10 之间。"""
    ui.show_replay_section(
        "播放倍速配置",
        "默认 1.0x，可设置 0.1 到 10x",
        "常用值: 0.5 / 1.0 / 2.0 / 5.0",
    )
    while True:
        rate_input = prompter.prompt_text(
            "播放倍速",
            "1.0",
            history_name="playback_rate",
            completer_words=["0.5", "1.0", "2.0", "5.0"],
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
    ui.show_replay_section(
        "问题标记配置",
        "回播结束后可记录问题时间点和现象备注",
        "输入 y 进入记录流程，输入 n 跳过",
    )
    if not prompter.get_confirm_input("是否记录？"):
        return None
    return ReplayIssueMarker(
        playback_start_sec=_get_issue_start_sec(),
        issue_description=_get_issue_description(),
    )


def _get_issue_start_sec() -> int:
    """读取问题时间点秒数，用于覆盖 issue 草稿中的 range(-s)。"""
    ui.show_replay_section(
        "问题时间点配置",
        "用于覆盖 issue 草稿中的 -s 时间点",
        "请输入非负整数秒数，例如 10",
    )
    while True:
        raw_value = prompter.prompt_text(
            "问题时间点",
            history_name="issue_start_sec",
        )
        if raw_value.isdigit():
            return int(raw_value)
        ui.print_status("请输入非负整数秒数", "WARN")


def _get_issue_description() -> str:
    """读取问题现象备注。"""
    ui.show_replay_section(
        "问题备注配置",
        "记录简短问题现象",
        "备注不能为空",
    )
    while True:
        issue_description = prompter.prompt_text(
            "简短备注",
            history_name="issue_description",
        )
        if issue_description:
            return issue_description
        ui.print_status("备注不能为空", "WARN")


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
