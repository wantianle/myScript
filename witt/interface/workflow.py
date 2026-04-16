from . import channel_prompter
from . import config_prompter
from . import prompter
from . import ui
from . import replay_workflow
from core.session import AppSession
from utils import parser


def _show_skipped_batches(skipped_batches) -> None:
    """输出被跳过批次的摘要信息。"""
    for skipped_batch in skipped_batches:
        ui.print_status(
            f"{skipped_batch.task_name}[{skipped_batch.soc_name}] 跳过: {skipped_batch.reason}",
            "ERROR",
        )


def _show_failed_batches(failed_batches) -> None:
    """输出失败批次的摘要信息。"""
    for failed_batch in failed_batches:
        ui.print_status(
            f"{failed_batch.task_name}[{failed_batch.soc_name}] 失败: {failed_batch.reason}",
            "WARN",
        )


def _load_task_entries(
    session: AppSession,
    need_export_path: bool = True,
):
    """执行查询并加载 manifest 中的任务列表。"""
    search_flow(session, need_export_path=need_export_path)
    task_list = parser.parse_manifest(session.ctx.manifest_path)
    if not task_list:
        ui.print_status("未找到相关 Record 记录", "ERROR")
        return []
    return task_list


def slice_progress(session: AppSession) -> None:
    """执行查询、切片和可选回放的一体化主流程。"""
    task_list = _load_task_entries(session, need_export_path=True)
    if not task_list:
        return
    selected_tasks = prompter.get_selected_indices(
        task_list, prompt="请选择要处理的 Tag 序号"
    )
    valid_tasks = [task_entry for task_entry in selected_tasks if task_entry.paths]
    if not valid_tasks:
        ui.print_status("所选序号无效或无路径数据", "ERROR")
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
        ui.print_status("下载队列为空", "WARN")
        _show_skipped_batches(planned_summary.skipped_batches)
        return
    ui.print_status(f"准备同步 {planned_summary.total_files} 个 Record 片段...")
    _show_skipped_batches(planned_summary.skipped_batches)
    download_summary = session.record_downloader.download_records(valid_tasks)
    _show_skipped_batches(download_summary.skipped_batches)
    _show_failed_batches(download_summary.failed_batches)
    if not download_summary.completed_batches:
        ui.print_status("没有成功完成的切片批次", "WARN")
        return
    ui.print_status("所有同步任务已完成！")
    if prompter.get_confirm_input("\n切片处理完成，是否立即回播数据?", True):
        replay_workflow.auto_replay_flow(
            session,
            replay_workflow.REPLAY_MODE_STANDARD,
        )


def full_source_progress(session: AppSession) -> None:
    """执行查询后直接回放原始 record 数据。"""
    task_list = _load_task_entries(session, need_export_path=False)
    if not task_list:
        return
    valid_tasks = [task_entry for task_entry in task_list if task_entry.paths]
    if not valid_tasks:
        ui.print_status("未找到可处理的有效 Tag 数据", "ERROR")
        return
    replay_workflow.full_source_replay_flow(session, valid_tasks)


def search_flow(
    session: AppSession,
    need_export_path: bool = True,
) -> None:
    """采集查询条件并执行 Record 检索脚本。"""
    config_prompter.get_basic_params(session.ctx)
    config_prompter.get_source_path_params(session.ctx)
    if need_export_path:
        config_prompter.get_export_path_params(session.ctx)
    config_prompter.get_split_params(session.ctx)
    session.runner.run_find_record()

full_progress = slice_progress
restore_environment_flow = replay_workflow.restore_environment_flow
traffic_light_replay_flow = replay_workflow.traffic_light_replay_flow
replay_flow = replay_workflow.replay_flow
auto_replay_flow = replay_workflow.auto_replay_flow
manual_replay_flow = replay_workflow.manual_replay_flow
