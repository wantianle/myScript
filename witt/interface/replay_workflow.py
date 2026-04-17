import os
import sys
import termios
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from . import channel_prompter
from . import config_prompter
from . import prompter
from . import replay_prompter
from . import ui
from core.models import ReplayHistoryEntry, ReplayRecord
from core.issue_draft import (
    IssueDraft,
    ReplayIssueMarker,
    format_issue_data_path,
    load_version_text,
    save_issue_draft,
)
from core.errors import RecordInfoError, PathMappingError
from core.session import AppSession
from utils import parser

REPLAY_MODE_STANDARD = "standard"
REPLAY_MODE_TRAFFIC_LIGHT = "traffic_light"
REPLAY_SOURCE_AUTO = "auto"
REPLAY_SOURCE_FULL_SOURCE = "full_source"
REPLAY_SOURCE_MANUAL = "manual"
REPLAY_SOURCE_HISTORY = "history"


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
        config_prompter.get_basic_params(session.ctx)
        session.init_logging()
        manual_replay_flow(session, REPLAY_MODE_TRAFFIC_LIGHT)
    else:
        config_prompter.get_basic_params(session.ctx)
        session.init_logging()
        config_prompter.update_dest_root(
            session.ctx,
            "输入要扫描的回灌路径(限/media下)",
        )
        auto_replay_flow(session, REPLAY_MODE_TRAFFIC_LIGHT)


def replay_flow(session: AppSession) -> None:
    """执行标准回放模式的入口编排。"""
    manual = prompter.get_confirm_input("手动选择文件播放？")
    if manual:
        config_prompter.get_basic_params(session.ctx)
        session.init_logging()
        manual_replay_flow(session, REPLAY_MODE_STANDARD)
    else:
        config_prompter.get_basic_params(session.ctx)
        session.init_logging()
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
    display_tag: str,
    issue_timestamp: str,
    start_sec: int,
    end_sec: int,
    issue_marker: Optional[ReplayIssueMarker] = None,
) -> None:
    """回播结束后统一处理 issue 草稿生成。"""
    playback_range_text = _format_playback_range(start_sec, end_sec)
    issue_description = IssueDraft.issue_description
    if issue_marker is not None:
        playback_range_text = _format_playback_range(
            issue_marker.playback_start_sec,
            end_sec,
        )
        issue_description = issue_marker.issue_description
    try:
        issue_paths = _build_issue_paths(
            [replay_record.path for replay_record in records],
            session.ctx.target_date,
            session.ctx.vehicle,
        )
    except ValueError as e:
        ui.print_status(str(e), "WARN")
        try:
            data_path_text = replay_prompter.get_issue_data_path_text(
                session.ctx.target_date,
                session.ctx.vehicle,
            )
            issue_paths = data_path_text.splitlines()
        except KeyboardInterrupt:
            ui.print_status("未提供准确 NAS 路径，已取消生成 issue 草稿", "WARN")
            return
    else:
        data_path_text = "\n".join(issue_paths)
    playback_command = _build_issue_playback_command(
        session,
        playback_plan.command,
        records,
        issue_paths,
    )
    issue_draft = IssueDraft(
        tag_text=display_tag or playback_plan.display_tag,
        vehicle=session.ctx.vehicle,
        target_date=session.ctx.target_date,
        playback_command=playback_command,
        data_path_text=data_path_text,
        version_text=load_version_text(session.ctx.logic.version),
        playback_rate=playback_plan.rate,
        playback_range_text=playback_range_text,
        playback_channels=list(getattr(session.ctx, "playback_blacklist", [])),
        issue_description=issue_description,
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


def _build_issue_paths(
    path_texts: List[str],
    target_date: str,
    vehicle: str,
) -> List[str]:
    """为 issue 草稿构建统一的 NAS 路径列表。"""
    return [
        format_issue_data_path(
            path_text,
            target_date,
            vehicle,
            "/media/nas/00.raw",
        )
        for path_text in path_texts
    ]


def _build_issue_playback_command(
    session: AppSession,
    playback_command: str,
    records: List[ReplayRecord],
    issue_paths: List[str],
) -> str:
    """将运行时回播命令中的实际路径替换为 issue 展示用 NAS 路径。"""
    issue_command = playback_command
    for replay_record, issue_path in zip(records, issue_paths):
        runtime_path = session.executor.map_path(replay_record.path)
        issue_command = issue_command.replace(runtime_path, issue_path)
    return issue_command


def _build_history_selection_label(
    records: List[ReplayRecord],
    display_tag: str,
    source_type: str,
) -> str:
    """生成历史记录中用于识别本次回播的摘要标题。"""
    if not records:
        return display_tag or source_type
    file_count = len(records)
    soc_names = sorted(
        {
            Path(replay_record.path).parent.name
            for replay_record in records
            if Path(replay_record.path).parent.name.startswith("soc")
        }
    )
    soc_text = ",".join(soc_names) if soc_names else "single"
    if source_type == REPLAY_SOURCE_MANUAL:
        return "manual | {0} | {1} files".format(
            Path(records[0].path).name,
            file_count,
        )
    return "{0} | {1} | {2} files".format(
        display_tag or Path(records[0].path).name,
        soc_text,
        file_count,
    )


def _build_replay_history_entry(
    session: AppSession,
    records: List[ReplayRecord],
    playback_plan,
    replay_mode: str,
    display_tag: str,
    issue_timestamp: str,
    start_sec: int,
    end_sec: int,
    source_type: str,
    selection_label: str,
) -> ReplayHistoryEntry:
    """构造当前回播的历史记录对象。"""
    replay_records = [
        ReplayRecord.from_cache_dict(replay_record.to_cache_dict())
        for replay_record in records
    ]
    return ReplayHistoryEntry(
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        source_type=source_type,
        replay_mode=replay_mode,
        selection_label=selection_label,
        display_tag=display_tag or playback_plan.display_tag,
        issue_timestamp=issue_timestamp,
        vehicle=str(getattr(session.ctx, "vehicle", "")),
        target_date=str(getattr(session.ctx, "target_date", "")),
        records=replay_records,
        start_sec=max(0, start_sec),
        end_sec=max(0, end_sec),
        playback_rate=playback_plan.rate,
        channel_filters=list(getattr(session.ctx, "playback_blacklist", [])),
    )


def _save_replay_history(
    session: AppSession,
    records: List[ReplayRecord],
    playback_plan,
    replay_mode: str,
    display_tag: str,
    issue_timestamp: str,
    start_sec: int,
    end_sec: int,
    source_type: str,
    selection_label: str,
) -> None:
    """保存本次回播参数到历史记录。"""
    history_repository = getattr(session, "replay_history_repository", None)
    if history_repository is None:
        return
    history_entry = _build_replay_history_entry(
        session,
        records,
        playback_plan,
        replay_mode,
        display_tag,
        issue_timestamp,
        start_sec,
        end_sec,
        source_type,
        selection_label,
    )
    try:
        history_repository.append(history_entry)
    except OSError as e:
        ui.print_status("保存回播历史失败: {0}".format(e), "WARN")


def _restore_replay_history_context(
    session: AppSession,
    history_entry: ReplayHistoryEntry,
) -> None:
    """恢复历史回播所需的最小上下文。"""
    session.ctx.logic.vehicle = history_entry.vehicle
    session.ctx.logic.target_date = history_entry.target_date
    session.ctx.playback_blacklist = list(history_entry.channel_filters)


def _validate_history_records(records: List[ReplayRecord]) -> bool:
    """检查历史回播依赖的文件是否仍然存在。"""
    if not records:
        ui.print_status("历史回播记录为空", "WARN")
        return False
    missing_paths = [
        replay_record.path
        for replay_record in records
        if not Path(replay_record.path).exists()
    ]
    if missing_paths:
        ui.print_status(
            "历史回播文件不存在: {0}".format(missing_paths[0]),
            "WARN",
        )
        return False
    return True


def _collect_issue_marker() -> Optional[ReplayIssueMarker]:
    """在回播结束后采集问题时间点标记。"""
    try:
        return replay_prompter.get_issue_marker()
    except KeyboardInterrupt:
        ui.print_status("已跳过问题时间点标记", "WARN")
        return None


def _replay_records(
    session: AppSession,
    records: List[ReplayRecord],
    replay_mode: str,
    loaded_msg: str,
    display_tag: str = "",
    issue_timestamp: str = "",
    source_type: str = REPLAY_SOURCE_AUTO,
    selection_label: str = "",
    replay_history_entry: Optional[ReplayHistoryEntry] = None,
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
    should_use_history_params = replay_history_entry is not None
    while True:
        ui.print_status(loaded_msg)
        use_history_params_this_round = (
            should_use_history_params and replay_history_entry is not None
        )
        if use_history_params_this_round and replay_history_entry is not None:
            start = replay_history_entry.start_sec
            end = replay_history_entry.end_sec
            playback_rate = replay_history_entry.playback_rate
            should_use_history_params = False
        else:
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
            if use_history_params_this_round:
                ui.print_status("历史参数无效，请重新调整播放时间和倍速", "WARN")
            continue
        last_playback_plan = playback_plan
        last_start = start
        last_end = end
        current_selection_label = selection_label or _build_history_selection_label(
            records,
            display_tag or playback_plan.display_tag,
            source_type,
        )
        ui.show_playback_info(
            tag=display_tag or playback_plan.display_tag,
            duration=playback_plan.duration,
            rate=playback_plan.rate,
            channels=getattr(session.ctx, "playback_blacklist", []) or None,
        )
        print(f"执行指令: \033[1;32m{playback_plan.command}\033[0m")
        _save_replay_history(
            session,
            records,
            playback_plan,
            replay_mode,
            display_tag or playback_plan.display_tag,
            issue_timestamp,
            start,
            end,
            source_type,
            current_selection_label,
        )
        try:
            session.executor.execute_interactive(playback_plan.command)
        except KeyboardInterrupt:
            ui.print_status("回播已中断", "WARN")
            break
        try:
            continue_replay = prompter.get_confirm_input("继续调整播放时间?")
        except KeyboardInterrupt:
            ui.print_status("回播已中断", "WARN")
            break
        if not continue_replay:
            break
    if last_playback_plan is not None:
        issue_marker = _collect_issue_marker()
        _post_replay_issue_draft(
            session,
            records,
            last_playback_plan,
            display_tag or last_playback_plan.display_tag,
            issue_timestamp,
            last_start,
            last_end,
            issue_marker=issue_marker,
        )


def replay_last_history_flow(session: AppSession) -> None:
    """重放最近一次回播历史。"""
    history_repository = getattr(session, "replay_history_repository", None)
    if history_repository is None:
        ui.print_status("当前会话未启用回播历史", "WARN")
        return
    history_entry = history_repository.load_last()
    if history_entry is None:
        ui.print_status("当前没有可重放的回播历史", "WARN")
        return
    _restore_replay_history_context(session, history_entry)
    session.init_logging()
    if not _validate_history_records(history_entry.records):
        return
    _replay_records(
        session,
        history_entry.records,
        history_entry.replay_mode,
        "重放上一次: {0}".format(history_entry.selection_label),
        display_tag=history_entry.display_tag,
        issue_timestamp=history_entry.issue_timestamp,
        source_type=REPLAY_SOURCE_HISTORY,
        selection_label=history_entry.selection_label,
        replay_history_entry=history_entry,
    )


def replay_history_flow(session: AppSession) -> None:
    """从历史记录中选择一次回播。"""
    history_repository = getattr(session, "replay_history_repository", None)
    if history_repository is None:
        ui.print_status("当前会话未启用回播历史", "WARN")
        return
    history_entries = _sort_replay_history_entries(history_repository.load())
    if not history_entries:
        ui.print_status("当前没有可重放的回播历史", "WARN")
        return
    history_entry = replay_prompter.select_replay_history_entry(history_entries)
    if history_entry is None:
        return
    _restore_replay_history_context(session, history_entry)
    session.init_logging()
    if not _validate_history_records(history_entry.records):
        return
    _replay_records(
        session,
        history_entry.records,
        history_entry.replay_mode,
        "历史回播已加载: {0}".format(history_entry.selection_label),
        display_tag=history_entry.display_tag,
        issue_timestamp=history_entry.issue_timestamp,
        source_type=REPLAY_SOURCE_HISTORY,
        selection_label=history_entry.selection_label,
        replay_history_entry=history_entry,
    )


def _sort_replay_history_entries(
    history_entries: List[ReplayHistoryEntry],
) -> List[ReplayHistoryEntry]:
    """按回播对应的 tag 时间倒序排列历史。"""
    return sorted(
        history_entries,
        key=lambda history_entry: _parse_history_issue_time(
            history_entry.issue_timestamp,
            history_entry.created_at,
        ),
        reverse=True,
    )


def _parse_history_issue_time(issue_timestamp: str, created_at: str) -> datetime:
    """优先解析 tag 时间，失败时回退到历史创建时间。"""
    for time_text in (issue_timestamp, created_at):
        try:
            return datetime.strptime(time_text, "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            continue
    return datetime.min


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
            source_type=REPLAY_SOURCE_AUTO,
            selection_label=_build_history_selection_label(
                target_records,
                selected_tag.tag,
                REPLAY_SOURCE_AUTO,
            ),
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
            source_type=REPLAY_SOURCE_FULL_SOURCE,
            selection_label=_build_history_selection_label(
                source_records,
                task_entry.name,
                REPLAY_SOURCE_FULL_SOURCE,
            ),
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
        source_type=REPLAY_SOURCE_MANUAL,
        selection_label=_build_history_selection_label(
            current_records,
            "manual",
            REPLAY_SOURCE_MANUAL,
        ),
    )
