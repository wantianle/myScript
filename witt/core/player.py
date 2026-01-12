import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any


class RecordPlayer:
    def __init__(self, session):
        self.ctx = session.ctx
        self.runner = session.runner
        self.executor = session.executor
        self.recorder = session.recorder

    @property
    def library_file(self):
        return self.ctx.work_dir / ".witt" / "local_library.json"

    def get_library(self) -> List[Dict[str, Any]]:
        # self.ctx.setup_logger()
        current_fp = self.ctx.get_library_fingerprint()
        if self.library_file.exists():
            try:
                data = json.loads(self.library_file.read_text(encoding="utf-8"))
                if data.get("fingerprint") == current_fp:
                    print(f"本地库状态未变，加载缓存{self.library_file}...")
                    return data.get("library", [])
            except Exception:
                pass

        logging.info(f"检测到目录状态变更，正在扫描本地库{self.ctx.work_dir}...")
        library_list = self.scan_local_library()
        save_obj = {"fingerprint": current_fp, "library": library_list}
        try:
            self.library_file.write_text(json.dumps(save_obj, indent=4, ensure_ascii=False))
        except Exception as e:
            logging.warning("缓存文件写入失败")
            raise e
        return library_list

    def scan_local_library(self) -> List[Dict[str, Any]]:
        library_map = {}
        for meta_file in self.ctx.work_dir.rglob("meta.json"):
            tag_dir = meta_file.parent
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                tag_name = meta["tag_info"]["name"]
                tag_entry = {
                    "tag": tag_name,
                    "time": meta["tag_info"]["time"],
                    "vehicle": meta.get("vehicle", tag_dir.parent.name),
                    "date": meta.get("date", tag_dir.parent.parent.name),
                    "socs": {},
                    "fast_meta": meta,
                }

                # meta["files"] 结构示例: {"soc1": ["f1.record", "f2.record"], "soc2": [...]}
                for soc_name, file_names in meta.get("files", {}).items():
                    soc_path = tag_dir / soc_name
                    if not soc_path.exists():
                        continue

                    record_details = []
                    for fname in file_names:
                        f_abs_path = soc_path / fname
                        if f_abs_path.exists():
                            record_details.append(
                                {
                                    "path": str(f_abs_path.absolute()),
                                    "begin": meta["tag_info"]["abs_start"],
                                    "duration": meta["tag_info"]["offset_bf"]
                                    + meta["tag_info"]["offset_af"],
                                }
                            )

                    if record_details:
                        record_details.sort(key=lambda x: x["begin"])
                        tag_entry["socs"][soc_name] = record_details

                library_map[str(tag_dir)] = tag_entry
            except Exception as e:
                logging.warning(f"元数据解析失败 [{meta_file}]: {e}")

        # # 兼容性扫描查询逻辑，用于旧数据（针对那些没有 meta.json 的老文件夹）
        for soc_dir in self.ctx.work_dir.rglob("*soc*"):
            tag_dir = soc_dir.parent

            if str(tag_dir) in library_map:
                continue

            record_details = []
            for f in soc_dir.glob("*.record*"):
                info = self.recorder.get_info(str(f.absolute()))
                if info["begin"]:
                    record_details.append(
                        {
                            "path": str(f.absolute()),
                            "begin": (
                                info["begin"].isoformat()
                                if isinstance(info["begin"], datetime)
                                else info["begin"]
                            ),
                            "duration": info["duration"],
                        }
                    )

            if record_details:
                record_details.sort(key=lambda x: x["begin"])
                if str(tag_dir) not in library_map:
                    library_map[str(tag_dir)] = {
                        "tag": tag_dir.name,
                        "time": "Unknown",
                        "vehicle": tag_dir.parent.name,
                        "date": tag_dir.parent.parent.name,
                        "socs": {},
                    }
                library_map[str(tag_dir)]["socs"][soc_dir.name] = record_details

        return sorted(list(library_map.values()), key=lambda x: x["time"])

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
        self.ctx.config["logic"]["version_json"] = Path(records[0]["path"]).parent

        # 边界钳位
        final_start = max(0, start_sec)
        final_end = total_duration
        if 0 < end_sec <= total_duration:
            final_end = end_sec

        # 逻辑保护
        if final_start >= final_end:
            logging.warning(
                f"检测到无效范围 [{start_sec}-{end_sec}]，自动调整为全量播放。"
            )
            final_start, final_end = 0, total_duration
        docker_paths = [self.executor.map_path(r["path"]) for r in records]
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
        self.executor.execute_interactive(full_cmd, self.runner)
