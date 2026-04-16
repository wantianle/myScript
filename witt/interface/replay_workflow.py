import os
import sys
import termios
from datetime import timedelta
from pathlib import Path
from typing import List

from . import channel_prompter
from . import config_prompter
from . import prompter
from . import replay_prompter
from . import ui
from core.models import ReplayRecord
from core.issue_draft import (
    IssueDraft,
    build_issue_data_path_text,
    load_version_text,
    save_issue_draft,
)
from core.errors import RecordInfoError, PathMappingError
from core.session import AppSession
from utils import parser

REPLAY_MODE_STANDARD = "standard"
REPLAY_MODE_TRAFFIC_LIGHT = "traffic_light"


def restore_environment_flow(
    session: AppSession,
    auto: bool = False,
    replay_mode: str = REPLAY_MODE_STANDARD,
) -> bool:
    """恢复运行环境并按模式启动回放相关栈。"""
    if not auto:
        session.ctx.logic.version = config_prompter.get_json_input()
        if not session.ctx.logic.version:
            ui.print_status("未提供版本文件，已取消环境恢复", "WARN")
            return False
    session.runner.restore_runtime_environment()
    if replay_mode == REPLAY_MODE_TRAFFIC_LIGHT:
        if prompter.get_confirm_input(
            "是否需要打开 Supervisor &  Debug_Driver-LiDAR & Dreamview & Multiviz？"
        ):
            session.runner.start_standard_replay_stack()
        if prompter.get_confirm_input(
            "是否需要打开 Debug_Driver-Camera & Perception-TrafficLight？"
        ):
            session.runner.start_traffic_light_stack()
    elif replay_mode == REPLAY_MODE_STANDARD:
        if prompter.get_confirm_input(
            "是否需要打开 Supervisor &  Debug_Driver-LiDAR & Dreamview & Multiviz？"
        ):
            session.runner.start_standard_replay_stack()
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
    return restore_environment_flow(
        session,
        auto=auto_version,
        replay_mode=replay_mode,
    )


def _update_playback_blacklist(
    session: AppSession,
    records: List[ReplayRecord],
    replay_mode: str,
) -> None:
    """根据当前回放记录更新频道过滤列表。"""
    if replay_mode != REPLAY_MODE_TRAFFIC_LIGHT:
        session.ctx.playback_blacklist = []
        return
    session.ctx.playback_blacklist = (
        channel_prompter.get_paths_channels(
            session,
            [replay_record.path for replay_record in records],
            prompter.get_confirm_input,
        )
        or []
    )


def _build_source_replay_records(
    session: AppSession,
    task_entry,
) -> List[ReplayRecord]:
    """根据查询结果为全量模式构造原始数据回放记录。"""
    ordered_paths = parser.sort_records([Path(path_text) for path_text in task_entry.paths])
    replay_begin = parser.str_to_time(task_entry.time) - timedelta(seconds=session.ctx.logic.before)
    replay_duration = session.ctx.logic.before + session.ctx.logic.after
    return [
        ReplayRecord(
            path=str(path_obj),
            begin=replay_begin,
            duration=replay_duration,
        )
        for path_obj in ordered_paths
    ]


def _format_playback_range(start_sec: int, end_sec: int) -> str:
    """格式化回播起始偏移，便于写入 issue 草稿的 range(-s)。"""
    del end_sec
    return "{0}s".format(max(0, start_sec))


def _post_replay_issue_draft(
    session: AppSession,
    records: List[ReplayRecord],
    playback_plan,
    replay_mode: str,
    display_tag: str,
    issue_timestamp: str,
    start_sec: int,
    end_sec: int,
    interrupted: bool,
) -> None:
    """回播结束后统一处理 issue 草稿生成。"""
    issue_draft = IssueDraft(
        tag_text=display_tag or playback_plan.display_tag,
        vehicle=session.ctx.vehicle,
        target_date=session.ctx.target_date,
        playback_command=playback_plan.command,
        data_path_text=build_issue_data_path_text(
            [replay_record.path for replay_record in records],
            session.ctx.target_date,
            session.ctx.vehicle,
        ),
        version_text=load_version_text(session.ctx.logic.version),
        playback_rate=playback_plan.rate,
        playback_range_text=_format_playback_range(start_sec, end_sec),
        playback_channels=list(getattr(session.ctx, "playback_blacklist", [])),
    )
    try:
        issue_path = save_issue_draft(
            session.ctx.work_dir,
            issue_draft,
            issue_timestamp=issue_timestamp,
        )
    except OSError as e:
        ui.print_status("生成 issue.md 失败: {0}".format(e), "ERROR")
        return
    ui.print_status("issue 草稿已生成: {0}".format(issue_path))


def _replay_records(
    session: AppSession,
    records: List[ReplayRecord],
    replay_mode: str,
    loaded_msg: str,
    display_tag: str = "",
    issue_timestamp: str = "",
) -> None:
    """执行一轮可重复调整时间窗的回放循环。"""
    if not records:
        ui.print_status("回播列表为空", "WARN")
        return
    if not _prepare_replay(session, records, replay_mode):
        return
    last_playback_plan = None
    last_start = 0
    last_end = 0
    interrupted = False
    while True:
        ui.print_status(loaded_msg)
        start, end = replay_prompter.get_playback_range()
        playback_rate = replay_prompter.get_playback_rate()
        try:
            playback_plan = session.player.build_playback_plan(
                records,
                start,
                end,
                playback_rate,
            )
        except (ValueError, PathMappingError) as e:
            ui.print_status(str(e), "WARN")
            continue
        last_playback_plan = playback_plan
        last_start = start
        last_end = end
        ui.show_playback_info(
            tag=display_tag or playback_plan.display_tag,
            duration=playback_plan.duration,
            rate=playback_plan.rate,
            channels=getattr(session.ctx, "playback_blacklist", []) or None,
        )
        print(f"执行指令: \033[1;32m{playback_plan.command}\033[0m")
        try:
            session.executor.execute_interactive(playback_plan.command)
        except KeyboardInterrupt:
            interrupted = True
            ui.print_status("回播已中断", "WARN")
            break
        try:
            continue_replay = prompter.get_confirm_input("继续调整播放时间?")
        except KeyboardInterrupt:
            interrupted = True
            ui.print_status("回播已中断", "WARN")
            break
        if not continue_replay:
            break
    if last_playback_plan is not None:
        _post_replay_issue_draft(
            session,
            records,
            last_playback_plan,
            replay_mode,
            display_tag or last_playback_plan.display_tag,
            issue_timestamp,
            last_start,
            last_end,
            interrupted,
        )


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
        _update_playback_blacklist(session, target_records, replay_mode)
        total_duration = max(replay_record.duration for replay_record in target_records)
        _replay_records(
            session,
            target_records,
            replay_mode,
            f"已加载 {len(target_records)} 个文件，总长 {total_duration}s",
            display_tag=selected_tag.tag,
            issue_timestamp=selected_tag.time,
        )


def full_source_replay_flow(session: AppSession, task_entries) -> None:
    """直接基于查询结果回放原始 record 数据，不生成任何导出文件。"""
    if not task_entries:
        ui.print_status("没有可回放的 Tag", "WARN")
        return
    find_record_output = getattr(session.ctx, "find_record_output", "")
    prompt_find_record_output = ""
    while True:
        task_entry = replay_prompter.select_source_task_entry(
            task_entries,
            find_record_output=prompt_find_record_output,
        )
        if task_entry is None:
            return
        # 首轮查询结果已由 find_record 脚本实时输出，回到选择页后再复用缓存文本。
        prompt_find_record_output = find_record_output
        source_records = _build_source_replay_records(session, task_entry)
        if not source_records:
            ui.print_status(f"{task_entry.name} 未匹配到可回放的原始数据", "WARN")
            continue
        _update_playback_blacklist(session, source_records, REPLAY_MODE_STANDARD)
        _replay_records(
            session,
            source_records,
            REPLAY_MODE_STANDARD,
            "全量模式已加载 "
            f"\033[1;32m{task_entry.name}\033[0m"
            f" | 共 {len(source_records)} 个文件 | 总长 {source_records[0].duration}s",
            display_tag=task_entry.name,
            issue_timestamp=task_entry.time,
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
    _update_playback_blacklist(session, current_records, replay_mode)
    _replay_records(
        session,
        current_records,
        replay_mode,
        f"已加载 {len(paths)} 个文件，总长 {tag_duration}s",
        issue_timestamp=tag_start.strftime("%Y-%m-%d %H:%M:%S"),
    )
