import questionary
from questionary import Choice
from pathlib import Path
from typing import List

from core.errors import RecordInfoError
from core.session import AppSession
from interface import ui


def select_channels_wizard(channels: List[dict], prompt: str) -> List[str]:
    """勾选式频道选择器"""
    choices = [
        Choice(
            title=f"{channel['name']:<20} (Msg Count: {channel.get('count', 0)})",
            value=channel["name"],
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


def get_channels(session: AppSession, tasks: List[dict]) -> List[dict]:
    """从多个 record 中提取频道并集，支持双 SOC 路径检查"""
    channels_map = {}
    socs = set()
    try:
        for task in tasks:
            path_list = task.get("paths", [])
            for path_text in path_list:
                soc = Path(path_text).parent.name[-4:]
                if soc in socs:
                    continue
                info = session.recorder.get_info(path_text)
                channels = info.get("channels", [])
                for channel in channels:
                    name = channel["name"]
                    if name not in channels_map:
                        channels_map[name] = channel.copy()
                        channels_map[name].setdefault("count", 0)
                    else:
                        channels_map[name]["count"] += channel.get("count", 0)
                socs.add(soc)
    except RecordInfoError as e:
        ui.print_status(str(e), "ERROR")
        raise
    except Exception as e:
        ui.print_status("频道获取失败", "ERROR")
        raise e
    return sorted(channels_map.values(), key=lambda channel: channel["name"])


def get_tasks_channels(session: AppSession, tasks: List[dict], confirm_prompt) -> List[str]:
    """过滤要播放的频道"""
    if not confirm_prompt("是否过滤 Channel?"):
        return []
    try:
        unique_channels = get_channels(session, tasks)
    except Exception as e:
        ui.print_status("频道获取失败", "ERROR")
        raise e
    return select_channels_wizard(unique_channels, prompt="请【选中】要删除的频道:")
