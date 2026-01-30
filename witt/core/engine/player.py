import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any
from interface import ui, workflow


class RecordPlayer:
    def __init__(self, session):
        self.session = session
        self.ctx = session.ctx
        self.executor = session.executor

    @property
    def library_file(self):
        return self.ctx.work_dir / ".witt" / "local_library.json"

    def get_library(self) -> List[Dict[str, Any]]:
        fp = self.ctx.get_library_fingerprint()
        if self.library_file.exists():
            data = json.loads(self.library_file.read_text(encoding="utf-8"))
            if data.get("fingerprint") == fp and data.get("library"):
                ui.print_status(f"本地库状态未变，加载缓存: {self.library_file}...")
                return data.get("library", [])
        ui.print_status(f"正在扫描本地库{self.ctx.work_dir}...")
        library_list = self.scan_local_library()
        save_obj = {"fingerprint": fp, "library": library_list}
        try:
            self.library_file.parent.mkdir(parents=True, exist_ok=True)
            self.library_file.write_text(
                json.dumps(save_obj, indent=4, ensure_ascii=False)
            )
        except Exception as e:
            ui.print_status("缓存文件写入失败", "ERROR")
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
                    "date": meta.get("date", tag_dir.parents[1].name),
                    "socs": {},
                    "last_update": meta.get("last_update"),
                }
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
                ui.print_status(f"[{meta_file}] 元数据解析失败...", "ERROR")
                raise e
        return sorted(list(library_map.values()), key=lambda x: x["time"])

    def play(
        self,
        records: List[Dict[str, Any]],
        start_sec: int = 0,
        end_sec: int = 0,
    ):
        if not records:
            ui.print_status("播放列表为空", "ERROR")
            return
        def ensure_dt(val):
            return datetime.fromisoformat(val) if isinstance(val, str) else val
        global_start = ensure_dt(records[0]["begin"])
        total_duration = max(r["duration"] for r in records)
        self.ctx.config["logic"]["version_json"] = Path(records[0]["path"]).parent
        # 构造指令
        docker_paths = [self.executor.map_path(r["path"]) for r in records]
        cmd_parts = ["cyber_recorder play", "-l", "-f", " ".join(docker_paths)]
        # 时间窗
        fmt = "%Y-%m-%d %H:%M:%S"
        final_start = max(0, start_sec)
        final_end = total_duration if end_sec <= 0 else min(end_sec, total_duration)
        cmd_parts.append(
            f'-b "{(global_start + timedelta(seconds=final_start)).strftime(fmt)}"'
        )
        cmd_parts.append(
            f'-e "{(global_start + timedelta(seconds=final_end)).strftime(fmt)}"'
        )

        full_cmd = " ".join(cmd_parts)
        ui.show_playback_info(
            tag=Path(records[0]["path"]).name[:20] + "...",
            duration=total_duration,
        )
        print(f"执行指令: \033[1;32m{full_cmd}\033[0m")

        workflow.restore_env_flow(self.session, True)
        self.executor.execute_interactive(full_cmd)
