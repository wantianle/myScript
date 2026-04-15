import os
import sys
import termios
from pathlib import Path
from typing import List

from . import config_prompter
from . import prompter
from . import replay_prompter
from . import ui
from core.models import ReplayRecord
from core.errors import RecordInfoError, PathMappingError
from core.session import AppSession

REPLAY_MODE_STANDARD = "standard"
REPLAY_MODE_TRAFFIC_LIGHT = "traffic_light"


def restore_environment_flow(
    session: AppSession,
    auto: bool = False,
    launch_mode: str = "prompt",
) -> bool:
    """恢复运行环境并按模式启动回放相关栈。"""
    if not auto:
        session.ctx.logic.version = config_prompter.get_json_input()
        if not session.ctx.logic.version:
            ui.print_status("未提供版本文件，已取消环境恢复", "WARN")
            return False
    session.runner.restore_runtime_environment()
    if launch_mode == "prompt":
        if prompter.get_confirm_input("是否需要打开 Dreamview & Multiviz？"):
            session.runner.start_standard_replay_stack()
        if prompter.get_confirm_input(
            "是否需要打开 Debug_Driver-LiDAR & Debug_Driver-Camera & Perception-TrafficLight？"
        ):
            session.runner.start_traffic_light_stack()
    elif launch_mode == REPLAY_MODE_STANDARD:
        session.runner.start_standard_replay_stack()
    elif launch_mode == REPLAY_MODE_TRAFFIC_LIGHT:
        session.runner.start_traffic_light_replay_stack()
    return True


def traffic_light_replay_flow(session: AppSession) -> None:
    """执行红绿灯回灌模式的入口编排。"""
    manual = prompter.get_confirm_input("手动选择文件回灌？")
    if manual:
        manual_replay_flow(session, REPLAY_MODE_TRAFFIC_LIGHT)
    else:
        config_prompter.get_basic_params(session.ctx)
        config_prompter.update_dest_root(
            session.ctx,
            "输入要扫描的回灌路径(限/media下)",
        )
        auto_replay_flow(session, REPLAY_MODE_TRAFFIC_LIGHT)


def replay_flow(session: AppSession) -> None:
    """执行标准回放模式的入口编排。"""
    manual = prompter.get_confirm_input("手动选择文件播放？")
    if manual:
        manual_replay_flow(session, REPLAY_MODE_STANDARD)
    else:
        config_prompter.get_basic_params(session.ctx)
        config_prompter.update_dest_root(
            session.ctx,
            "输入要扫描的回播路径(限/media下)",
        )
        auto_replay_flow(session, REPLAY_MODE_STANDARD)


def _resolve_version_from_records(
    session: AppSession,
    records: List[ReplayRecord],
) -> bool:
    """从当前回放记录中推断版本文件路径。"""
    version_path = next(Path(records[0].path).parent.glob("version*"), None)
    session.ctx.logic.version = version_path or ""
    return version_path is not None


def _prepare_replay(
    session: AppSession,
    records: List[ReplayRecord],
    replay_mode: str,
) -> bool:
    """为回放准备环境和工具栈。"""
    auto_version = _resolve_version_from_records(session, records)
    launch_mode = "prompt" if replay_mode == REPLAY_MODE_STANDARD else REPLAY_MODE_TRAFFIC_LIGHT
    return restore_environment_flow(
        session,
        auto=auto_version,
        launch_mode=launch_mode,
    )


def _replay_records(
    session: AppSession,
    records: List[ReplayRecord],
    replay_mode: str,
    loaded_msg: str,
) -> None:
    """执行一轮可重复调整时间窗的回放循环。"""
    if not records:
        ui.print_status("回播列表为空", "WARN")
        return
    if not _prepare_replay(session, records, replay_mode):
        return
    while True:
        ui.print_status(loaded_msg)
        start, end = replay_prompter.get_playback_range()
        try:
            playback_plan = session.player.build_playback_plan(records, start, end)
        except (ValueError, PathMappingError) as e:
            ui.print_status(str(e), "WARN")
            continue
        ui.show_playback_info(
            tag=playback_plan.display_tag,
            duration=playback_plan.duration,
        )
        print(f"执行指令: \033[1;32m{playback_plan.command}\033[0m")
        session.executor.execute_interactive(playback_plan.command)
        if not prompter.get_confirm_input("继续调整播放时间?"):
            break


def auto_replay_flow(
    session: AppSession,
    replay_mode: str = REPLAY_MODE_STANDARD,
) -> None:
    """自动扫描目录并选择回放条目。"""
    while True:
        library_result = session.player.load_library()
        if library_result.cache_hit:
            ui.print_status(f"本地库状态未变，加载缓存: {library_result.cache_path}...")
        else:
            ui.print_status(f"已扫描本地库 {session.ctx.work_dir}...")
        library = library_result.library
        if not library:
            ui.print_status("本地目录为空！", "WARN")
            return
        selected_tag = replay_prompter.select_playback_entry(
            library,
            session.ctx.vehicle,
            session.ctx.target_date,
        )
        if not selected_tag:
            break
        target_records = replay_prompter.select_replay_records(selected_tag)
        if not target_records:
            continue
        total_duration = max(replay_record.duration for replay_record in target_records)
        _replay_records(
            session,
            target_records,
            replay_mode,
            f"已加载 {len(target_records)} 个文件，总长 {total_duration}s",
        )


def manual_replay_flow(
    session: AppSession,
    replay_mode: str = REPLAY_MODE_STANDARD,
) -> None:
    """手动选择文件后执行回放。"""
    paths = replay_prompter.get_manual_replay_paths()
    if not paths:
        return
    if os.name == "posix":
        termios.tcflush(sys.stdin, termios.TCIFLUSH)
    try:
        info_start = session.recorder.get_info(str(paths[0]))
        info_end = session.recorder.get_info(str(paths[-1]))
    except RecordInfoError as e:
        ui.print_status(str(e), "ERROR")
        return
    tag_start = info_start.begin
    tag_end = info_end.end
    tag_duration = int((tag_end - tag_start).total_seconds())
    current_records = [
        ReplayRecord(path=str(path_obj), begin=tag_start, duration=tag_duration)
        for path_obj in paths
    ]
    _replay_records(
        session,
        current_records,
        replay_mode,
        f"已加载 {len(paths)} 个文件，总长 {tag_duration}s",
    )


restore_env_flow = restore_environment_flow
replay_traffic_light_flow = traffic_light_replay_flow
play_flow = replay_flow
auto_play = auto_replay_flow
manual_play = manual_replay_flow
