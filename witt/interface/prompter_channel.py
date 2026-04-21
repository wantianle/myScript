from pathlib import Path
from typing import Callable, Dict, List, Set

from core.errors import RecordInfoError
from core.models import ChannelInfo, TaskEntry
from core.session import AppSession
from . import prompter, ui


def select_channels_wizard(channels: List[ChannelInfo], prompt: str) -> List[str]:
    """显示频道列表并返回选中的频道名。"""
    current_channels = list(channels)
    search_keyword = ""
    while True:
        ui.show_channel_candidates(
            current_channels,
            search_keyword=search_keyword,
            total_count=len(channels),
        )
        raw_choice = prompter.prompt_text(
            "{0}\n输入序号/范围选择要删除的频道"
            " | 支持 1,3,5 / 2-6 / 0 5 7-15 / 0"
            " | /关键字筛选 | / 清空筛选 | 回车跳过".format(prompt),
            history_name="channel_selection",
            completer_words=[
                str(index) for index in range(1, len(current_channels) + 1)
            ],
        )
        if not raw_choice:
            return []
        next_keyword = prompter.resolve_filter_keyword(raw_choice)
        if next_keyword is not None:
            next_channels = _filter_channels(channels, next_keyword)
            search_keyword = next_keyword
            current_channels = next_channels if next_keyword else list(channels)
            continue
        if not current_channels:
            ui.show_input_feedback(
                "当前筛选结果为空",
                hint="请调整关键字或输入 / 清空筛选",
            )
            continue
        try:
            selected_indices = prompter.parse_index_expression(
                raw_choice,
                len(current_channels),
            )
        except ValueError:
            ui.show_input_feedback(
                "输入无效，请重新选择",
                hint="支持序号、范围和反选表达式",
            )
            continue
        if not selected_indices:
            ui.show_input_feedback(
                "未选中任何频道，请检查输入",
                hint="可输入序号、范围或 0 进行反选",
            )
            continue
        return [current_channels[index - 1].name for index in selected_indices]


def _filter_channels(
    channels: List[ChannelInfo],
    keyword: str,
) -> List[ChannelInfo]:
    """按关键字过滤频道。"""
    return [
        channel
        for channel in channels
        if prompter.matches_search_keyword(
            keyword,
            [channel.name, channel.count],
        )
    ]


def _get_paths_channels(
    session: AppSession,
    path_texts: List[str],
) -> List[ChannelInfo]:
    """从多个 record 路径中提取频道并集，支持双 SOC 路径检查。"""
    channels_map: Dict[str, ChannelInfo] = {}
    seen_socs: Set[str] = set()
    try:
        for path_text in path_texts:
            soc = Path(path_text).parent.name[-4:]
            if soc in seen_socs:
                continue
            info = session.recorder.get_info(path_text)
            for channel in info.channels:
                channel_name = channel.name
                if channel_name not in channels_map:
                    channels_map[channel_name] = ChannelInfo(
                        name=channel.name,
                        count=channel.count,
                    )
                else:
                    channels_map[channel_name].count += channel.count
            seen_socs.add(soc)
    except RecordInfoError as e:
        ui.show_result_section(
            "频道分析",
            "读取频道信息失败",
            "ERROR",
            details=[str(e)],
            next_step="检查 record 文件是否可读后重试",
        )
        raise
    except Exception as e:
        ui.show_result_section(
            "频道分析",
            "频道获取失败",
            "ERROR",
            details=[str(e)],
            next_step="检查 record 信息解析链路后重试",
        )
        raise RuntimeError("频道获取失败") from e
    return sorted(channels_map.values(), key=lambda channel: channel.name)


def get_paths_channels(
    session: AppSession,
    path_texts: List[str],
    confirm_prompt: Callable[[str, bool], bool],
) -> List[str]:
    """交互式选择指定 record 路径中要过滤掉的频道。"""
    if not confirm_prompt("是否过滤 Channel?", False):
        return []
    unique_channels = _get_paths_channels(session, path_texts)
    return select_channels_wizard(unique_channels, prompt="请【选中】要删除的频道:")

