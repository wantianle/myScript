import parser
from utils import handles
from pathlib import Path
import logging

def full_progress(session):
    parser.get_basic_params(session.ctx.config)
    parser.get_path_params(session.ctx.config)
    try:
        session.record_query()
        task_list = handles.parse_manifest(session.ctx.manifest_path)
        selected_list = parser.get_selected_indices(task_list)
        if input("是否压缩 Record? [y/N] (回车跳过): ").lower() == "y":
            # 这里怎么简化，我只需要channel名单去过滤信息
            session.record_compress(Path(task_list[0]["paths"][0]))
        valid_tasks = [t for t in selected_list if t.get("paths")]
        for task in valid_tasks:
            time, name, paths = task["time"], task["name"], task["paths"]
            tag_dt = handles.str_to_time(time)
            print(f"\n>>> 正在处理: {name} {tag_dt}")
            for f in paths:
                session.record_slice(Path(f), tag_dt)
        session.record_download(selected_list)
        if input("\n是否立即回播数据? [y/N] (回车跳过): ").lower() == "y":
            session.task_play()
    except Exception as e:
        logging.error(f"全流程执行失败: {e}")
        raise e
        # logging.debug(traceback.format_exc())
