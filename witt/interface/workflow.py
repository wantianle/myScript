import os
import sys
import termios
from pathlib import Path
from . import prompter
from . import ui
from core.session import AppSession
from utils import parser

REPLAY_MODE_STANDARD = "standard"
REPLAY_MODE_TRAFFIC_LIGHT = "traffic_light"


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
        session.ctx.config["logic"]["blacklist"] = (
            prompter.get_tasks_channels(session, valid_tasks) or ""
        )
        session.downloader.download_record(valid_tasks)
        if prompter.get_confirm_input("\n切片处理完成，是否立即回播数据?", True):
            auto_replay_flow(session, REPLAY_MODE_STANDARD)
    except Exception as e:
        raise e


def search_flow(session: AppSession):
    prompter.get_basic_params(session.ctx.config)
    prompter.get_path_params(session.ctx.config)
    session.runner.run_find_record()


def restore_environment_flow(
    session: AppSession,
    auto: bool = False,
    launch_mode: str = "prompt",
):
    if not auto:
        session.ctx.config["logic"]["version"] = prompter.get_json_input()
        if not session.ctx.config["logic"]["version"]:
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


def traffic_light_replay_flow(session: AppSession):
    manual = prompter.get_confirm_input("手动选择文件回灌？")
    if manual:
        manual_replay_flow(session, REPLAY_MODE_TRAFFIC_LIGHT)
    else:
        prompter.get_basic_params(session.ctx.config)
        session.ctx.config["host"]["dest_root"] = prompter.get_user_input(
            "输入要扫描的回灌路径(限/media下)",
            session.ctx.config["host"]["dest_root"],
        )
        auto_replay_flow(session, REPLAY_MODE_TRAFFIC_LIGHT)


def replay_flow(session: AppSession):
    manual = prompter.get_confirm_input("手动选择文件播放？")
    if manual:
        manual_replay_flow(session, REPLAY_MODE_STANDARD)
    else:
        prompter.get_basic_params(session.ctx.config)
        session.ctx.config["host"]["dest_root"] = prompter.get_user_input(
            "输入要扫描的回播路径(限/media下)",
            session.ctx.config["host"]["dest_root"],
        )
        auto_replay_flow(session, REPLAY_MODE_STANDARD)

def _resolve_version_from_records(session: AppSession, records: list) -> bool:
    version_path = next(Path(records[0]["path"]).parent.glob("version*"), None)
    session.ctx.config["logic"]["version"] = version_path or ""
    return version_path is not None


def _prepare_replay(session: AppSession, records: list, replay_mode: str) -> bool:
    auto_version = _resolve_version_from_records(session, records)
    launch_mode = "prompt" if replay_mode == REPLAY_MODE_STANDARD else REPLAY_MODE_TRAFFIC_LIGHT
    return restore_environment_flow(
        session,
        auto=auto_version,
        launch_mode=launch_mode,
    )


def _replay_records(session: AppSession, records: list, replay_mode: str, loaded_msg: str):
    if not records:
        ui.print_status("回播列表为空", "WARN")
        return
    if not _prepare_replay(session, records, replay_mode):
        return
    while True:
        ui.print_status(loaded_msg)
        range_in = input(
            "调整播放时间 (改变起点 5 | 限制范围 5-10 | 回车全播): "
        ).strip()
        start, end = parser.parse_range_logic(range_in)
        session.player.play(records, start, end)
        if not prompter.get_confirm_input("继续调整播放时间?"):
            break


def auto_replay_flow(session: AppSession, replay_mode: str = REPLAY_MODE_STANDARD):
    """
    自动扫描指定路径下的文件，专门负责回播界面的展示和用户输入处理
    """
    while True:
        library = session.player.get_library()
        if not library:
            ui.print_status("本地目录为空！", "WARN")
            return
        ui.show_playback_library(library, session.ctx.vehicle, session.ctx.target_date)

        tag_idx = input("\n选择播放序号 (回车取消): ").strip()
        if not tag_idx:
            break
        selected_tag = library[int(tag_idx) - 1]
        socs = sorted(list(selected_tag["socs"].keys()))
        for i, s in enumerate(socs, 1):
            print(f"  [{i}] {s}")
        if len(socs) > 1:
            print(f"  [{len(socs) + 1}] All")

        target_records = []
        choice = input("选择要播放的 SOC (默认 1): ").strip() or "1"
        if choice.isdigit() and int(choice) <= len(socs):
            target_records = selected_tag["socs"][socs[int(choice) - 1]]
        else:
            for s in socs:
                target_records.extend(selected_tag["socs"][s])
        total_duration = max(r["duration"] for r in target_records)
        _replay_records(
            session,
            target_records,
            replay_mode,
            f"已加载 {len(target_records)} 个文件，总长 {total_duration}s",
        )


def manual_replay_flow(session: AppSession, replay_mode: str = REPLAY_MODE_STANDARD):
    """
    手动播放循环，保留文件列表，支持多次调整时间播放
    """
    try:
        ui.show_manual_play_header()
        paths = prompter.get_dragged_input()
        if not paths:
            return
        # 清空缓冲区，避免污染
        if os.name == "posix":
            termios.tcflush(sys.stdin, termios.TCIFLUSH)
        info_start = session.recorder.get_info(str(paths[0]))
        info_end = session.recorder.get_info(str(paths[-1]))
        tag_start = info_start["begin"]
        tag_end = info_end["end"]
        tag_duration = int((tag_end - tag_start).total_seconds())
        current_records = [
            {"path": str(p), "begin": tag_start, "duration": tag_duration}
            for p in paths
        ]
        _replay_records(
            session,
            current_records,
            replay_mode,
            f"已加载 {len(paths)} 个文件，总长 {tag_duration}s",
        )
    except Exception as e:
        raise e


restore_env_flow = restore_environment_flow
replay_traffic_light_flow = traffic_light_replay_flow
play_flow = replay_flow
auto_play = auto_replay_flow
manual_play = manual_replay_flow
