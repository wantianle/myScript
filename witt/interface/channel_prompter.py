import questionary
from questionary import Choice
from pathlib import Path
from typing import Callable, Dict, List, Set

from core.errors import RecordInfoError
from core.models import ChannelInfo, TaskEntry
from core.session import AppSession
from interface import ui


def select_channels_wizard(channels: List[ChannelInfo], prompt: str) -> List[str]:
    """显示可勾选的频道列表并返回选中的频道名。"""
    choices = [
        Choice(
            title=f"{channel.name:<20} (Msg Count: {channel.count})",
            value=channel.name,
        )
        for channel in channels
    ]
    selected = questionary.checkbox(
        prompt,
        choices=choices,
        style=questionary.Style(
            [
                ("pointer", "fg:cyan bold"),
                ("highlighted", "fg:cyan bold"),
                ("selected", "fg:red"),
            ]
        ),
    ).ask()
    return selected if selected is not None else []


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
        ui.print_status(str(e), "ERROR")
        raise
    except Exception as e:
        ui.print_status("频道获取失败", "ERROR")
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


def get_tasks_channels(
    session: AppSession,
    tasks: List[TaskEntry],
    confirm_prompt: Callable[[str, bool], bool],
) -> List[str]:
    """交互式选择要过滤掉的频道。"""
    return get_paths_channels(
        session,
        [path_text for task_entry in tasks for path_text in task_entry.paths],
        confirm_prompt,
    )
