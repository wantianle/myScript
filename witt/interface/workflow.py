from pathlib import Path
from typing import List, Optional, Sequence

from . import channel_prompter
from . import config_prompter
from . import prompter
from . import ui
from . import replay_workflow
from core.engine.downloader import FailedBatch, SkippedBatch
from core.errors import ScriptExecutionError
from core.models import TaskEntry
from core.session import AppSession


def _task_entry_search_values(task_entry: TaskEntry) -> List[str]:
    """构造 Tag 查询结果的关键字匹配字段。"""
    return [
        task_entry.id,
        task_entry.time,
        task_entry.name,
        "soc1" if task_entry.soc_paths.get("soc1") else "",
        "soc2" if task_entry.soc_paths.get("soc2") else "",
        str(len(task_entry.soc_paths.get("soc1", []))),
        str(len(task_entry.soc_paths.get("soc2", []))),
        str(len(task_entry.paths)),
    ]


def _show_skipped_batches(skipped_batches: Sequence[SkippedBatch]) -> None:
    """输出被跳过批次的摘要信息。"""
    for skipped_batch in skipped_batches:
        ui.show_notice_section(
            "切片批次",
            f"{skipped_batch.task_name}[{skipped_batch.soc_name}] 跳过",
            "WARN",
            details=[str(skipped_batch.reason)],
        )


def _show_failed_batches(failed_batches: Sequence[FailedBatch]) -> None:
    """输出失败批次的摘要信息。"""
    for failed_batch in failed_batches:
        ui.show_notice_section(
            "切片批次",
            f"{failed_batch.task_name}[{failed_batch.soc_name}] 失败",
            "ERROR",
            details=[str(failed_batch.reason)],
        )


def _load_task_entries(
    session: AppSession,
    need_export_path: bool = True,
    allow_remote: bool = True,
    preset_mode: Optional[int] = None,
    split_window_name: str = "切片窗口",
) -> List[TaskEntry]:
    """执行查询并加载任务列表。"""
    task_list = search_flow(
        session,
        need_export_path=need_export_path,
        allow_remote=allow_remote,
        preset_mode=preset_mode,
        split_window_name=split_window_name,
    )
    if task_list is None:
        return []
    if not task_list:
        ui.show_result_section(
            "查询结果",
            "未找到相关 Record 记录",
            "ERROR",
            next_step="调整车辆、日期或源路径后重试",
        )
        return []
    return task_list


def slice_progress(session: AppSession) -> None:
    """执行查询、切片和可选回放的一体化主流程。"""
    ui.show_flow_section(
        "切片模式",
        "查询 Record -> 选择 Tag -> 切片 -> 可选回播",
        "适合先做批量切片，再进入回播验证",
    )
    task_list = _load_task_entries(session, need_export_path=True)
    if not task_list:
        return
    selected_tasks = prompter.get_selected_indices(
        task_list,
        prompt="请选择要处理的 Tag 序号",
        render_items=ui.show_source_task_entries,
        search_values_getter=_task_entry_search_values,
        history_name="slice_task_selection",
    )
    if not selected_tasks:
        return
    valid_tasks = [task_entry for task_entry in selected_tasks if task_entry.paths]
    if not valid_tasks:
        ui.show_result_section(
            "切片结果",
            "所选序号无效或无路径数据",
            "ERROR",
            next_step="重新选择包含有效路径的 Tag",
        )
        return
    session.ctx.logic.blacklist = (
        channel_prompter.get_tasks_channels(
            session,
            valid_tasks,
            prompter.get_confirm_input,
        )
        or []
    )
    planned_summary = session.record_downloader.plan_download(valid_tasks)
    if planned_summary.total_files <= 0:
        ui.show_result_section(
            "切片结果",
            "下载队列为空",
            "WARN",
            details=["没有可执行的切片批次"],
            next_step="检查筛选的 Tag、路径和切片时间窗",
        )
        _show_skipped_batches(planned_summary.skipped_batches)
        return
    ui.show_progress_section(
        "切片执行中",
        "准备同步 {0} 个 Record 片段".format(planned_summary.total_files),
        details=[
            "已选中 {0} 个 Tag".format(len(valid_tasks)),
        ],
        hint="即将开始下载与切片流程",
    )
    _show_skipped_batches(planned_summary.skipped_batches)
    download_summary = session.record_downloader.download_records(valid_tasks)
    _show_skipped_batches(download_summary.skipped_batches)
    _show_failed_batches(download_summary.failed_batches)
    if not download_summary.completed_batches:
        ui.show_result_section(
            "切片结果",
            "没有成功完成的切片批次",
            "WARN",
            next_step="检查失败或跳过原因后重试",
        )
        return
    ui.show_result_section(
        "切片结果",
        "所有同步任务已完成！",
        details=[
            "已完成 {0} 个切片批次".format(
                len(download_summary.completed_batches)
            )
        ],
        next_step="可立即进入回播，或返回 REPL 继续其他操作",
    )
    if prompter.get_confirm_input("\n切片处理完成，是否立即回播数据?", True):
        replay_workflow.auto_replay_flow(
            session,
            replay_workflow.REPLAY_MODE_STANDARD,
        )


def full_source_progress(
    session: AppSession,
    preset_mode: Optional[int] = None,
) -> None:
    """执行查询后直接回放原始 record 数据。"""
    ui.show_flow_section(
        "原始数据回放（不切片）",
        "查询 Record -> 选择 Tag -> 直接回放原始数据",
        "不生成导出目录，直接基于原始记录构造回播",
    )
    task_list = _load_task_entries(
        session,
        need_export_path=False,
        allow_remote=False,
        preset_mode=preset_mode,
        split_window_name="回播窗口",
    )
    if not task_list:
        return
    valid_tasks = [task_entry for task_entry in task_list if task_entry.paths]
    if not valid_tasks:
        ui.show_result_section(
            "原始数据回放",
            "未找到可处理的有效 Tag 数据",
            "ERROR",
            next_step="检查查询结果是否包含有效原始路径",
        )
        return
    replay_workflow.full_source_replay_flow(session, valid_tasks)


def auto_replay_progress(session: AppSession) -> None:
    """采集参数后自动扫描本地目录并执行标准回放。"""
    ui.show_flow_section(
        "自动回播模式",
        "扫描本地目录并从回播库中选择条目",
        "适合已经准备好本地回播目录的场景",
    )
    config_prompter.get_basic_params(session.ctx)
    session.init_logging()
    config_prompter.update_dest_root(
        session.ctx,
        "输入要扫描的回播路径(限/media下)",
    )
    replay_workflow.auto_replay_flow(
        session,
        replay_workflow.REPLAY_MODE_STANDARD,
    )


def manual_replay_progress(session: AppSession) -> None:
    """手动选择回播文件并执行标准回放。"""
    ui.show_flow_section(
        "手动回播模式",
        "直接粘贴或拖拽 record 文件/目录后回播",
        "支持单文件、多文件或目录输入",
    )
    config_prompter.get_basic_params(session.ctx)
    session.init_logging()
    replay_workflow.manual_replay_flow(
        session,
        replay_workflow.REPLAY_MODE_STANDARD,
    )


def manual_replay_progress_with_paths(session: AppSession, path_texts: List[str]) -> None:
    """手动回播入口，直接使用命令提供的路径列表。"""
    ui.show_flow_section(
        "手动回播模式",
        "直接使用命令提供的 record 路径进入回播",
        "仍会复用基础参数采集和标准回播流程",
    )
    config_prompter.get_basic_params(session.ctx)
    session.init_logging()
    replay_paths = [Path(path_text) for path_text in path_texts]
    replay_workflow.manual_replay_paths_flow(
        session,
        replay_paths,
        replay_workflow.REPLAY_MODE_STANDARD,
    )


def replay_history_progress(session: AppSession) -> None:
    """先浏览历史记录，再选择一次回播。"""
    ui.show_flow_section(
        "历史回播模式",
        "浏览历史记录并按序号回播",
        "支持从列表选择，也支持 history last / history <序号>",
    )
    replay_workflow.replay_history_flow(session)


def search_flow(
    session: AppSession,
    need_export_path: bool = True,
    allow_remote: bool = True,
    preset_mode: Optional[int] = None,
    split_window_name: str = "切片窗口",
) -> Optional[List[TaskEntry]]:
    """采集查询条件并执行 Record 检索脚本。"""
    config_prompter.get_basic_params(session.ctx)
    session.init_logging()
    config_prompter.get_source_path_params(
        session.ctx,
        allow_remote=allow_remote,
        preset_mode=preset_mode,
    )
    if need_export_path:
        config_prompter.get_export_path_params(session.ctx)
    config_prompter.get_split_params(session.ctx, split_window_name)
    try:
        return session.runtime.run_find_record()
    except ScriptExecutionError as e:
        ui.show_result_section(
            "查询结果",
            e.summary,
            "ERROR",
            details=e.details,
            next_step="检查数据源路径、车辆、日期和执行环境后重试",
        )
        return None

full_progress = slice_progress
restore_environment_flow = replay_workflow.restore_environment_flow
traffic_light_replay_flow = replay_workflow.traffic_light_replay_flow
replay_flow = replay_workflow.replay_flow
auto_replay_flow = replay_workflow.auto_replay_flow
manual_replay_flow = replay_workflow.manual_replay_flow
replay_history_flow = replay_workflow.replay_history_flow
