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
            logging.error("所选序号无效或无路径数据"); return

        if parser.confirm_action("是否对 Record 执行 Channel 过滤压缩?"):
            blacklist = parser.select_channels_interactive(
                session.recorder, Path(valid_tasks[0]["paths"][0])
            )
            session.record_compress(Path(valid_tasks[0]["paths"][0]), blacklist)

        session.record_split(valid_tasks)

        if parser.confirm_action("\n处理完成，是否立即回播数据?", default=True):
            playflow(session)

    except Exception as e:
        logging.error(f"全流程执行失败: {e}")
        logging.debug(f"Detail Error: {e}", exc_info=True)


def playflow(session):
    """
    专门负责回播界面的展示和用户输入处理
    """
    while True:
        library = session.player.get_library()
        if not library:
            print("本地没有任何 Record 数据")
            return

        ui.show_playback_library(library, session.ctx.vehicle, session.ctx.target_date)

        tag_idx = input("\n请选择播放序号 (回车取消): ").strip()

        if not tag_idx:
            break
        try:
            selected_tag = library[int(tag_idx) - 1]
            socs = list(selected_tag["socs"].keys())
            for i, s in enumerate(socs, 1):
                print(f"  [{i}] {s}")

            if len(socs) > 1:
                print(f"  [{len(socs) +1 }] All")
            idx = int(input("选择 SOC (默认 1): ").strip() or "1")

            target_records = []
            if idx <= len(socs):
                soc = socs[idx - 1]
                target_records = selected_tag["socs"][soc]
            else:
                print(">>> 合并所有 SOC 数据进行同步回播...")
                for s in socs:
                    target_records.extend(selected_tag["socs"][s])

            start, end = handles.parser_range_logic(input(
                "播放范围 (5 | 10-20 | 回车全播): "
            ).strip())

            session.task_play(target_records, start, end)
        except (ValueError, IndexError):
            print("输入序号无效")
            continue
        if not parser.confirm_action("继续回播?", True):
            break
