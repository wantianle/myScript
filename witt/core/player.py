import re
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
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
                    print(f"本地库状态未变，加载缓存{self.library_file}...")
                    return data.get("library", [])
            except Exception:
                pass

        print(f"检测到目录状态变更，正在扫描本地库{self.dest_root}...")
        library_list = self.scan_local_library()
        save_obj = {"fingerprint": current_fp, "library": library_list}
        self.library_file.write_text(json.dumps(save_obj, indent=4, ensure_ascii=False))
        return library_list

    def scan_local_library(self) -> List[Dict[str, Any]]:
        """
        扫描下载目录结构，构建结构化本地库
        """
        library_map = {}

        for soc_dir in self.dest_root.rglob("*soc*"):
            if not soc_dir.is_dir(): continue
            tag_dir = soc_dir.parent
            readme_path = soc_dir / "README.md"
            tag_time = "Unknown Time"
            if readme_path.exists():
                content = readme_path.read_text(encoding="utf-8")
                match = re.search(r"- \*\*tag：\*\* ([\d-]+\s[\d:]+)", content)
                if match:
                    tag_time = match.group(1)
            vehicle_dir = tag_dir.parent
            date_dir = vehicle_dir.parent
            record_details = []
            for f in soc_dir.iterdir():
                if ".record" in f.name:
                    d_path = self.executor.to_docker_path(str(f.absolute()))
                    info = self.record_mgr.get_info(d_path)
                    if info["begin"]:
                        record_details.append(
                            {
                                "path": str(f.absolute()),
                                "begin": info["begin"].isoformat(),
                                "duration": info.get("duration", 0),
                            }
                        )

            if not record_details:
                continue

            # 按时间排序片段
            record_details.sort(key=lambda x: x["begin"])
            if not record_details:
                continue
            tag_name = tag_dir.name
            if tag_name not in library_map:
                library_map[tag_name] = {
                    "tag": tag_name,
                    "time": tag_time,
                    "vehicle": vehicle_dir.name,
                    "date": date_dir.name,
                    "socs": {},
                }
            library_map[tag_name]["socs"][soc_dir.name] = record_details
        library_list = list(library_map.values())
        library_list.sort(key=lambda x: x["time"])
        self.library_file.write_text(
            json.dumps(library_list, indent=4, ensure_ascii=False)
        )
        return library_list

    def play(self, records: List[Dict[str, Any]], start_sec: int = 0, end_sec: int = 0):
        """
        执行播放：支持相对偏移转绝对时间
        """
        if not records:
            logging.error("播放列表为空")
            return
        # 路径转换与元数据获取
        def ensure_dt(val):
            if isinstance(val, str):
                return datetime.fromisoformat(val)
            return val

        earliest_begin = ensure_dt(records[0]["begin"])
        total_duration = sum(item["duration"] for item in records)

        # 边界钳位
        final_start = max(0, start_sec)
        final_end = total_duration
        if 0 < end_sec <= total_duration:
            final_end = end_sec

        # 逻辑保护
        if final_start >= final_end:
            logging.warning(f"检测到无效范围 [{start_sec}-{end_sec}]，自动调整为全量播放。")
            final_start, final_end = 0, total_duration
        docker_paths = [self.executor.to_docker_path(r["path"]) for r in records]
        cmd_parts = ["cyber_recorder play", "-l", "-f", " ".join(docker_paths)]

        # 时间窗口换算 (逻辑封装)
        fmt = "%Y-%m-%d %H:%M:%S"
        begin_abs = earliest_begin + timedelta(seconds=final_start)
        end_abs = earliest_begin + timedelta(seconds=final_end)

        cmd_parts.append(f'-b "{begin_abs.strftime(fmt)}"')
        cmd_parts.append(f'-e "{end_abs.strftime(fmt)}"')

        full_cmd = " ".join(cmd_parts)

        # 输出
        tag_display = Path(records[0]["path"]).parents[1].name
        print(f"\n正在播放事件: \033[1;32m{tag_display}\033[0m")
        print(f"执行指令: \033[0;32m{full_cmd}\033[0m")

        # 交互式执行
        self.executor.execute_interactive(full_cmd)
