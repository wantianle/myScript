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
            ui.show_notice_section(
                "环境恢复",
                "未提供版本文件，已取消环境恢复",
                "WARN",
            )
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
    ui.show_flow_section(
        "红绿灯回灌模式",
        "选择自动扫描或手动文件进入回灌回播",
        "适合回灌红绿灯相关问题排查，会按模式补充环境恢复和频道过滤",
    )
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
    ui.show_flow_section(
        "标准回播模式",
        "选择自动扫描或手动文件进入标准回播",
        "适合直接从本地目录或手动路径进入回播",
    )
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
    issue_paths = _try_build_issue_paths(
        [replay_record.path for replay_record in records],
        session.ctx.target_date,
        session.ctx.vehicle,
    )
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
        data_path_text="",
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
        ui.show_result_section(
            "Issue 草稿",
            "生成 issue.md 失败",
            "ERROR",
            details=[str(e)],
            next_step="检查工作目录写权限后重试",
        )
        return
    ui.show_result_section(
        "Issue 草稿",
        "issue 草稿已生成",
        details=[str(issue_path)],
        next_step="可检查并补充 issue 内容",
    )


def _try_build_issue_paths(
    path_texts: List[str],
    target_date: str,
    vehicle: str,
) -> List[str]:
    """尽力构造 issue 用展示路径，失败时退化为空列表。"""
    try:
        return _build_issue_paths(path_texts, target_date, vehicle)
    except ValueError as e:
        ui.show_notice_section(
            "Issue 草稿",
            "已保留运行时回播命令，不再补录数据路径",
            "WARN",
            details=[str(e)],
        )
        return []


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
    if not issue_paths or len(issue_paths) != len(records):
        return playback_command
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
        ui.show_result_section(
            "回播历史",
            "保存回播历史失败",
            "WARN",
            details=[str(e)],
            next_step="检查历史文件目录权限后重试",
        )


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
        ui.show_result_section(
            "历史回播",
            "历史回播记录为空",
            "WARN",
            next_step="重新选择历史记录或清空无效历史",
        )
        return False
    missing_paths = [
        replay_record.path
        for replay_record in records
        if not Path(replay_record.path).exists()
    ]
    if missing_paths:
        ui.show_result_section(
            "历史回播",
            "历史回播文件不存在",
            "WARN",
            details=[str(missing_paths[0])],
            next_step="重新选择历史记录，或清空无效历史",
        )
        return False
    return True


def _collect_issue_marker() -> Optional[ReplayIssueMarker]:
    """在回播结束后采集问题时间点标记。"""
    try:
        return replay_prompter.get_issue_marker()
    except KeyboardInterrupt:
        ui.show_result_section(
            "问题标记",
            "已跳过问题时间点标记",
            "WARN",
            next_step="如需补录，可重新回播后再次记录",
        )
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
        ui.show_result_section(
            "回播准备",
            "回播列表为空",
            "WARN",
            next_step="重新选择回播条目或检查本地目录",
        )
        return
    if not _prepare_replay(session, records, replay_mode):
        return
    last_playback_plan = None
    last_start = 0
    last_end = 0
    should_use_history_params = replay_history_entry is not None
    while True:
        ui.show_progress_section(
            "回播准备",
            loaded_msg,
            hint="可继续调整播放时间、范围和倍速",
        )
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
            ui.show_input_feedback(str(e))
            if use_history_params_this_round:
                ui.show_input_feedback(
                    "历史参数无效，请重新调整播放时间和倍速",
                )
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
            command=playback_plan.command,
        )
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
            ui.show_notice_section(
                "回播执行",
                "回播已中断",
                "WARN",
            )
            break
        try:
            continue_replay = prompter.get_confirm_input("继续调整播放时间?")
        except KeyboardInterrupt:
            ui.show_notice_section(
                "回播执行",
                "回播已中断",
                "WARN",
            )
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


def replay_history_flow(session: AppSession) -> None:
    """先浏览历史记录，再选择一次回播。"""
    history_entries = get_sorted_replay_history_entries(session)
    if not history_entries:
        ui.show_result_section(
            "历史回播",
            "当前没有可重放的回播历史",
            "WARN",
            next_step="先完成一次回播，或使用其他模式进入回播",
        )
        return
    ui.browse_replay_history(history_entries)
    while True:
        history_index = replay_prompter.select_replay_history_index(history_entries)
        if history_index is None:
            return
        if history_index == 0:
            if not prompter.get_confirm_input("确认清空全部历史记录？"):
                continue
            session.replay_history_repository.clear()
            ui.show_notice_section(
                "历史回播",
                "已清空全部回播历史",
            )
            return
        history_entry = history_entries[history_index - 1]
        if not replay_history_entry(session, history_entry, validate_only=True):
            continue
        replay_history_entry(session, history_entry)
        return


def get_sorted_replay_history_entries(session: AppSession) -> List[ReplayHistoryEntry]:
    """读取并按创建时间倒序返回历史记录。"""
    history_repository = getattr(session, "replay_history_repository", None)
    if history_repository is None:
        ui.show_result_section(
            "历史回播",
            "当前会话未启用回播历史",
            "WARN",
            next_step="检查会话配置或重新初始化应用会话",
        )
        return []
    return _sort_replay_history_entries(history_repository.load())


def replay_latest_history_entry(session: AppSession) -> bool:
    """直接回播最新一条历史记录。"""
    history_entries = get_sorted_replay_history_entries(session)
    if not history_entries:
        ui.show_result_section(
            "历史回播",
            "当前没有可重放的回播历史",
            "WARN",
            next_step="先完成一次回播，或使用 history 浏览历史",
        )
        return False
    return replay_history_entry(session, history_entries[0])


def replay_history_by_index(session: AppSession, history_index: int) -> bool:
    """按展示序号回播一条历史记录。"""
    history_entries = get_sorted_replay_history_entries(session)
    if not history_entries:
        ui.show_result_section(
            "历史回播",
            "当前没有可重放的回播历史",
            "WARN",
            next_step="先完成一次回播，或使用 history 浏览历史",
        )
        return False
    if history_index < 1 or history_index > len(history_entries):
        ui.show_result_section(
            "历史回播",
            "历史序号超出范围: {0}".format(history_index),
            "WARN",
            next_step="使用 history 浏览可用序号后重试",
        )
        return False
    return replay_history_entry(session, history_entries[history_index - 1])


def replay_history_entry(
    session: AppSession,
    history_entry: ReplayHistoryEntry,
    validate_only: bool = False,
) -> bool:
    """校验并回播一条历史记录。"""
    if not _history_entry_is_replayable(history_entry):
        ui.show_result_section(
            "历史回播",
            "所选历史记录路径失效，无法回播",
            "WARN",
            next_step="重新选择历史记录，或输入 0 清空历史",
        )
        return False
    if validate_only:
        return True
    _restore_replay_history_context(session, history_entry)
    session.init_logging()
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
    return True


def _sort_replay_history_entries(
    history_entries: List[ReplayHistoryEntry],
) -> List[ReplayHistoryEntry]:
    """按历史记录创建时间倒序排列。"""
    return sorted(
        history_entries,
        key=lambda history_entry: _parse_history_created_at(history_entry.created_at),
        reverse=True,
    )


def _parse_history_created_at(created_at: str) -> datetime:
    """解析历史记录创建时间，失败时退化为最小时间。"""
    try:
        return datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return datetime.min


def _history_entry_is_replayable(history_entry: ReplayHistoryEntry) -> bool:
    """判断历史记录中的回播文件当前是否仍然有效。"""
    return bool(history_entry.records) and all(
        Path(replay_record.path).exists()
        for replay_record in history_entry.records
    )


def auto_replay_flow(
    session: AppSession,
    replay_mode: str = REPLAY_MODE_STANDARD,
) -> None:
    """自动扫描目录并选择回放条目。"""
    while True:
        library_result = session.player.load_library()
        if library_result.cache_hit:
            ui.show_progress_section(
                "自动回播",
                "本地库状态未变，正在加载缓存",
                details=[str(library_result.cache_path)],
                hint="正在读取回播库条目",
            )
        else:
            ui.show_progress_section(
                "自动回播",
                "已扫描本地库",
                details=[str(session.ctx.work_dir)],
                hint="正在构建回播条目列表",
            )
        library = library_result.library
        if not library:
            ui.show_result_section(
                "自动回播",
                "本地目录为空",
                "WARN",
                details=[str(session.ctx.work_dir)],
                next_step="检查扫描目录，或先完成切片/同步",
            )
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
        ui.show_result_section(
            "全量回播",
            "没有可回放的 Tag",
            "WARN",
            next_step="先执行查询，或调整车辆和日期条件",
        )
        return
    while True:
        task_entry = replay_prompter.select_source_task_entry(task_entries)
        if task_entry is None:
            return
        source_records = _build_source_replay_records(session, task_entry)
        if not source_records:
            ui.show_result_section(
                "全量回播",
                "{0} 未匹配到可回放的原始数据".format(task_entry.name),
                "WARN",
                next_step="重新选择其他 Tag 或调整查询条件",
            )
            continue
        _update_playback_blacklist(session, source_records, REPLAY_MODE_STANDARD)
        _replay_records(
            session,
            source_records,
            REPLAY_MODE_STANDARD,
            "全量模式已加载 {0} | 共 {1} 个文件 | 总长 {2}s".format(
                task_entry.name,
                len(source_records),
                source_records[0].duration,
            ),
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
    manual_replay_paths_flow(session, paths, replay_mode)


def manual_replay_paths_flow(
    session: AppSession,
    paths: List[Path],
    replay_mode: str = REPLAY_MODE_STANDARD,
) -> None:
    """基于已给定文件路径列表执行手动回放。"""
    if not paths:
        return
    if os.name == "posix":
        termios.tcflush(sys.stdin, termios.TCIFLUSH)
    try:
        info_start = session.recorder.get_info(str(paths[0]))
        info_end = session.recorder.get_info(str(paths[-1]))
    except RecordInfoError as e:
        ui.show_result_section(
            "手动回播模式",
            "读取 record 信息失败",
            "ERROR",
            details=[str(e)],
            next_step="检查输入路径和 record 文件后重试",
        )
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
