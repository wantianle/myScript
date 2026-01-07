import json
import logging
from pathlib import Path
from datetime import timedelta
from typing import List, Dict, Any


class RecordPlayer:
    def __init__(self, session):
        self.config = session.config
        self.ctx = session.ctx
        self.executor = session.record_mgr.executor  # 执行器
        self.record_mgr = session.record_mgr  # 逻辑器
        self.dest_root = Path(self.config["host"]["dest_root"])
        self.library_file = self.dest_root / "local_library.json"

    def get_library(self) -> List[Dict[str, Any]]:
        current_fp = self.ctx.get_library_fingerprint()
        if self.library_file.exists():
            try:
                data = json.loads(self.library_file.read_text(encoding="utf-8"))
                if data.get("fingerprint") == current_fp:
                    logging.info("本地库状态未变，加载缓存...")
                    return data.get("library", [])
            except Exception:
                pass

        logging.info("检测到目录状态变更，正在扫描本地库...")
        library_list = self.scan_local_library()
        save_obj = {"fingerprint": current_fp, "library": library_list}
        self.library_file.write_text(json.dumps(save_obj, indent=4, ensure_ascii=False))
        return library_list

    def scan_local_library(self) -> List[Dict[str, Any]]:
        """
        扫描下载目录结构，构建结构化本地库
        """
        library_map = {}
        if not self.dest_root.exists():
            return []

        for soc_dir in self.dest_root.rglob("*soc*"):
            if not soc_dir.is_dir():
                continue
            tag_dir = soc_dir.parent
            date_dir = tag_dir.parent
            vehicle_dir = date_dir.parent
            records = [
                str(f.absolute()) for f in soc_dir.iterdir() if ".record" in f.name
            ]
            if not records:
                continue
            tag_name = tag_dir.name
            if tag_name not in library_map:
                library_map[tag_name] = {
                    "tag": tag_name,
                    "vehicle": vehicle_dir.name,
                    "date": date_dir.name,
                    "socs": {},
                }
            library_map[tag_name]["socs"][soc_dir.name] = sorted(records)
        library_list = list(library_map.values())
        self.library_file.write_text(
            json.dumps(library_list, indent=4, ensure_ascii=False)
        )
        return library_list

    def play(self, records: List[str], start_sec: int = 0, end_sec: int = 0):
        """
        执行播放：支持相对偏移转绝对时间
        """
        if not records:
            logging.error("播放列表为空")
            return
        # 路径转换与元数据获取
        first_file = self.executor.to_docker_path(records[0])
        info = self.record_mgr.get_info(first_file)
        total_duration = info.get("duration")

        # 边界钳位
        final_start = max(0, start_sec)
        if end_sec <= 0 or end_sec > total_duration:
            logging.warning(f"结束时间异常，调整为记录总时长 {total_duration} 秒。")
            final_end = total_duration
        else:
            final_end = end_sec

        # 逻辑保护
        if final_start >= final_end:
            logging.warning(f"检测到无效范围 [{start_sec}-{end_sec}]，自动调整为全量播放。")
            final_start, final_end = 0, total_duration
        docker_files = [self.executor.to_docker_path(f) for f in records]
        cmd_parts = ["cyber_recorder play", "-l", "-f", " ".join(docker_files)]

        # 时间窗口换算 (逻辑封装)
        fmt = "%Y-%m-%d %H:%M:%S"
        begin_abs = info["begin"] + timedelta(seconds=final_start)
        end_abs = info["begin"] + timedelta(seconds=final_end)

        cmd_parts.append(f'-b "{begin_abs.strftime(fmt)}"')
        cmd_parts.append(f'-e "{end_abs.strftime(fmt)}"')

        full_cmd = " ".join(cmd_parts)

        # 输出
        tag_display = Path(records[0]).parents[1].name
        print(f"\n正在播放事件: \033[1;32m{tag_display}\033[0m")
        print(f"执行指令: \033[0;32m{full_cmd}\033[0m")

        # 交互式执行
        self.executor.execute_interactive(full_cmd)
