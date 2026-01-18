from datetime import timedelta
from pathlib import Path
from . import prompter
from . import ui
from core.session import AppSession
from utils import parser

def full_progress(session: AppSession):
    try:
        search_flow(session)
        task_list = parser.parse_manifest(session.ctx.manifest_path)
        if not task_list:
            ui.print_status("未找到相关 Record 记录", "ERROR")
            return
        selected_tasks = prompter.get_selected_indices(
            task_list, prompt="请选择要处理的 Tag 序号"
        )
        valid_tasks = [t for t in selected_tasks if t.get("paths")]
        if not valid_tasks:
            ui.print_status("所选序号无效或无路径数据", "ERROR")
            return
        if prompter.get_confirm_input("是否对 Record 执行 Channel 过滤压缩?"):
            session.ctx.config["logic"]["blacklist"] = prompter.get_selected_channels(
                session.recorder, Path(valid_tasks[0]["paths"][0])
            )
        else:
            session.ctx.config["logic"]["blacklist"] = ""
        session.downloader.download_record(valid_tasks)
        if prompter.get_confirm_input("\n处理完成，是否立即回播数据?", default=True):
            play_flow(session, False)
    except Exception as e:
        ui.print_status(f"全流程执行失败...", "ERROR")
        raise e


def search_flow(session: AppSession):
    prompter.get_basic_params(session.ctx.config)
    prompter.get_path_params(session.ctx.config)
    ui.print_status("正在执行数据检索...")
    session.runner.run_find_record()


def compress_flow(session: AppSession):
    """Channel 过滤压缩"""
    target_path = Path(input("需要压缩的 record 文件完整路径: ").strip())
    blacklist = prompter.get_selected_channels(session.recorder, target_path)
    session.ctx.config["logic"]["blacklist"] = blacklist
    ui.print_status(f">>> 执行数据压缩，删除 channels {len(blacklist)} 个")
    record_slice(session, target_path)


def slice_flow(session: AppSession):
    prompter.get_basic_params(session.ctx.config)
    prompter.get_split_params(session.ctx.config)
    record_files, tag_dt = prompter.get_record_files(session)
    for f in record_files:
        record_slice(session, f, tag_dt)


def record_slice(session: AppSession, input_path: Path, tag_dt=None):
    """时间截取切片"""
    tag_start, tag_end = None, None
    if tag_dt:
        tag_start = tag_dt - timedelta(seconds=session.ctx.config["logic"]["before"])
        tag_end = tag_dt + timedelta(seconds=session.ctx.config["logic"]["after"])
    return session.recorder.split(
        host_in=str(input_path),
        host_out=str(input_path.with_suffix(".split")),
        start_dt=tag_start,
        end_dt=tag_end,
        blacklist=session.ctx.config["logic"]["blacklist"],
    )


def restore_env_flow(session: AppSession, auto: bool = False):
    if not auto:
        session.ctx.config["logic"]["version_json"] = prompter.get_json_input()
    session.runner.run_restore_env()
    if prompter.get_confirm_input("是否需要打开 Dreamview & Multiviz", False):
        session.runner.run_tools()


def play_flow(session: AppSession, flag: bool = True):
    """
    专门负责回播界面的展示和用户输入处理
    """
    if flag: prompter.get_basic_params(session.ctx.config)
    session.ctx.config["host"]["dest_root"] = prompter.get_user_input(
        "请输入回播数据根目录(仅限/media下)",
        session.ctx.config["host"]["dest_root"],
    )
    while True:
        library = session.player.get_library()
        if not library:
            ui.print_status("本地目录为空，进入手动回播模式...", "WARN")
            manual_play_flow(session)
            return
        ui.show_playback_library(library, session.ctx.vehicle, session.ctx.target_date)
        tag_idx = input("\n请选择播放序号 (回车取消): ").strip()
        if not tag_idx:
            break
        prompter.get_cached_playback(session, library[int(tag_idx) - 1])


def manual_play_flow(session: AppSession):
    """
    手动播放循环：保留文件列表，支持多次调整时间播放
    """
    ui.show_manual_play_header()
    raw_input = prompter.get_dragged_input()
    if raw_input.lower() == "q":
        return
    paths = prompter.get_dragged_paths(raw_input)
    if not paths:
        ui.print_status("无效路径", "ERROR")
        return
    info_start = session.recorder.get_info(str(paths[0]))
    info_end = session.recorder.get_info(str(paths[-1]))
    g_start = info_start["begin"]
    g_end = info_end["end"]
    g_duration = int((g_end - g_start).total_seconds())
    current_records = [
        {"path": str(p), "begin": g_start, "duration": g_duration} for p in paths
    ]
    while True:
        ui.print_status(f"已加载 {len(paths)} 个文件，总长 {g_duration}s")
        selected_channels = prompter.get_selected_channels_for_play(
            session, current_records
        )
        range_in = input("输入播放范围 (如 0-60, 回车全播): ").strip()
        s, e = parser.parse_range_logic(range_in)
        session.player.play(
            current_records, s, e, selected_channels
        )
        if not prompter.get_confirm_input("继续调整该组文件播放?"):
            break
