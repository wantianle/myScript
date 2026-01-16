# witt/workflow.py

from core.session import AppSession
from utils import handles
import parser
import logging
from pathlib import Path
import ui


def full_progress(session: AppSession):
    try:
        session.record_query()

        task_list = handles.parse_manifest(session.ctx.manifest_path)
        if not task_list:
            logging.error("未找到相关 Record 记录")
            return

        selected_tasks = parser.get_selected_indices(
            task_list, prompt="请选择要处理的 Tag 序号"
        )
        valid_tasks = [t for t in selected_tasks if t.get("paths")]
        if not valid_tasks:
            logging.error("所选序号无效或无路径数据")
            return

        if parser.confirm_action("是否对 Record 执行 Channel 过滤压缩?"):
            blacklist = parser.select_channels_interactive(
                session.recorder, Path(valid_tasks[0]["paths"][0])
            )
            session.record_compress(Path(valid_tasks[0]["paths"][0]), blacklist)
        else:
            session.ctx.config["logic"]["blacklist"] = ""
        session.record_split(valid_tasks)

        if parser.confirm_action("\n处理完成，是否立即回播数据?", default=True):
            playflow(session)

    except Exception as e:
        ui.print_status(f"全流程执行失败: {e}", "ERR")
        logging.exception("Workflow Crash Traceback:")


def playflow(session):
    """
    专门负责回播界面的展示和用户输入处理
    """
    while True:
        library = session.player.get_library()
        if not library:
            logging.warning("未检测到本地缓存库，进入手动拖拽模式...")
            manual_play_loop(session)
            return

        ui.show_playback_library(library, session.ctx.vehicle, session.ctx.target_date)

        tag_idx = input("\n请选择播放序号 (回车取消): ").strip()
        if not tag_idx:
            break
        parser.get_cached_playback(session, library[int(tag_idx) - 1])


def manual_play_loop(session):
    """
    手动播放循环：保留文件列表，支持多次调整时间播放
    """
    ui.show_manual_play_header()
    raw_input = input("请拖入文件/目录: ").strip()
    if raw_input.lower() == "q":
        return

    paths = parser.parse_dragged_paths(raw_input)
    if not paths:
        logging.error("无效路径")
        return

    info_start = session.recorder.get_info(str(paths[0]))
    info_end = session.recorder.get_info(str(paths[-1]))

    g_start = info_start["begin"]
    g_end = info_end["end"]
    g_duration = int((g_end - g_start).total_seconds())

    current_records = []
    for p in paths:
        current_records.append(
            {
                "path": str(p),
                "begin": g_start.isoformat(),
                "duration": g_duration,
            }
        )

    while True:
        logging.info(f"已加载 {len(paths)} 个文件，总长 {g_duration}s")

        # 选择频道
        selected_channels = parser.select_playback_channels(session, current_records)

        # 选择时间
        range_in = input("\n输入播放范围 (如 0-60, 回车全播): ").strip()
        s, e = handles.parse_range_logic(range_in)

        # 执行播放
        session.task_play(current_records, s, e, selected_channels)

        if not parser.confirm_action("继续调整该组文件播放?"):
            if parser.confirm_action("是否更换一组文件?"):
                manual_play_loop(session)
            break
