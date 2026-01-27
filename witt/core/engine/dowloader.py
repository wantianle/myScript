import logging
import json
import os
import shutil
from alive_progress import alive_bar
from datetime import datetime, timedelta
from pathlib import Path

from interface import ui
from utils import parser


class RecordDownloader:
    def __init__(self, session):
        self.session = session
        self.ctx = session.ctx
        self.recorder = session.recorder
        self.remote_user = self.ctx.config["remote"]["user"]
        self.remote_ip = self.ctx.config["remote"]["ip"]

    # @property
    # def mode(self):
    #     return self.ctx.config["logic"]["mode"]

    @property
    def dest_root(self):
        return Path(self.ctx.config["host"]["dest_root"])

    def _prepare_dir(self, target_dir: Path):
        """
        彻底清理目标目录，确保没有旧数据干扰
        """
        if target_dir.exists():
            shutil.rmtree(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

    def save_contract(self, task, save_dir, file_infos):
        """保存元数据，实现信息透传"""
        tag_dir = save_dir.parent
        meta_path = tag_dir / "meta.json"
        dt_tag = parser.str_to_time(task["time"])
        bf, af = (
            int(self.ctx.config["logic"]["before"]),
            int(self.ctx.config["logic"]["after"]),
        )
        contract = {
            "tag_info": {
                "name": task["name"],
                "time": task["time"],
                "offset_bf": bf,
                "offset_af": af,
                "abs_start": (dt_tag - timedelta(seconds=bf)).isoformat(),
                "abs_end": (dt_tag + timedelta(seconds=af)).isoformat(),
            },
            "vehicle": self.ctx.vehicle,
            "date": self.ctx.target_date,
            "last_update": {},
            "files": {},
        }
        if meta_path.exists():
            try:
                old_contract = json.loads(meta_path.read_text(encoding="utf-8"))
                contract["last_update"] = old_contract["last_update"]
                contract["files"] = old_contract["files"]
            except Exception:
                ui.print_status("元数据文件损坏，执行全量重写", "WARN")
        current_soc = file_infos[0][2]
        contract["files"][current_soc] = [Path(f[1]).name for f in file_infos]
        contract["last_update"][current_soc] = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        meta_path.write_text(json.dumps(contract, indent=4, ensure_ascii=False))

    def post_process_task(self, task, save_dir, file_infos):
        """生成元数据文件、 README 和 version.json"""
        # 生成元数据文件
        self.save_contract(task, save_dir, file_infos)
        # 同步 version.json
        src_dir = Path(file_infos[0][0]).parent
        v_src = src_dir / "version.json"
        v_dest = save_dir / "version.json"
        # try:
            # if self.mode == 3:
            #     remote_src = f"{self.remote_user}@{self.remote_ip}:{v_src}"
            #     down_cmd = ["scp", "-q", "-o", remote_src, v_dest]
            #     env_c = os.environ.copy()
            #     env_c["LC_ALL"] = "C"
            #     result = subprocess.run(
            #         down_cmd, env=env_c, capture_output=True, text=True
            #     )
            #     if result.returncode != 0:
            #         ui.print_status(
            #             f"拷贝 {task['name']}: version.json 文件失败: {result.stderr}",
            #             "ERROR",
            #         )
            # else:
        if os.path.exists(v_src):
            shutil.copy2(v_src, v_dest)
        # except Exception as e:
        #     ui.print_status(f"拷贝 {task['name']}: version.json 文件失败", "ERROR")
        #     raise e
        # 生成 README
        v_content = v_dest.read_text() if v_dest.exists() else "N/A"
        records_str = " ".join([Path(f[1]).name for f in file_infos])
        nas_path = save_dir.relative_to(Path(self.ctx.config["host"]["dest_root"]))
        duration = int(self.ctx.config["logic"]["before"]) + int(self.ctx.config["logic"]["after"])
        readme_content = f"""- **tag：** {task["time"]} {task["name"]} {duration}s
- **问题描述：**
> 填写补充描述
- **预期结果：**
> 填写正确情况
- **车辆软硬件信息：**
```json
{v_content}
```
- **数据路径：**
```bash
{self.ctx.config["host"]["nas_root"]}/{nas_path}
```
- **数据时刻：**
```bash
{records_str}
```
"""
        readme_path = save_dir / "README.md"
        readme_path.write_text(readme_content, encoding="utf-8")
        logging.info(f"[TASK_COMPLETE] Tag: {task['name']} | Saved to: {save_dir}")
        logging.info(f"  Files: {[Path(f[1]).name for f in file_infos]}")

    def _sync_file(self, src, dest, task):
        """
        同步的核心逻辑：
        1. 生成 .split 文件，全量覆盖
        2. 清理中间文件
        """
        # 环境准备
        logic = self.ctx.config["logic"]
        tag_dt = parser.str_to_time(task["time"])
        t_start = tag_dt - timedelta(seconds=int(logic["before"]))
        t_end = tag_dt + timedelta(seconds=int(logic["after"]))
        blacklist = logic.get("blacklist")
        if blacklist:
            logging.info(f"[RECORDER_COMPRESS] Blacklist: {','.join(blacklist)}")
        # if self.ctx.config["logic"]["mode"] != 3:
        self.session.recorder.split(
            host_in=src,
            host_out=dest,
            start_dt=t_start,
            end_dt=t_end,
            blacklist=blacklist,
        )
        # else:
        #     remote_out = f"{src}.split"
        #     self.session.executor.remove(remote_out)
        #     success = self.session.recorder.split(
        #         host_in=src,
        #         host_out=remote_out,
        #         start_dt=t_start,
        #         end_dt=t_end,
        #         blacklist=blacklist,
        #     )
        #     if success:
        #         self.session.executor.fetch_file(remote_out, dest)
        #         self.session.executor.remove(remote_out)
        #     else:
        #         logging.error(f"[SSH] 切片失败: {src}")

    def _get_task_save_dir(self, task, soc_name) -> Path:
        """统一管理保存路径规则"""
        return self.ctx.get_task_dir(task["id"], task["name"], soc_name)

    def download_record(self, task_list):
        """
        负责高层调度和进度条
        """
        download_queue = []
        prepared_dirs = set()
        for task in task_list:
            for soc_name, paths in task["soc_paths"].items():
                if not paths:
                    continue
                save_dir = self._get_task_save_dir(task, soc_name)
                if save_dir not in prepared_dirs:
                    self._prepare_dir(save_dir)
                    prepared_dirs.add(save_dir)
                save_dir.mkdir(parents=True, exist_ok=True)
                for p in paths:
                    download_queue.append(
                        {
                            "src": Path(p),
                            "dest": save_dir / (Path(p).name + ".split"),
                            "task": task,
                            "save_dir": save_dir,
                            "soc_name": soc_name,
                        }
                    )
        if not download_queue:
            ui.print_status("下载队列为空", "WARN")
            return
        ui.print_status(f"准备同步 {len(download_queue)} 个 Record 片段...")
        # 执行下载流水线
        with alive_bar(
            len(download_queue),
            title="Progress",
            theme="classic",
            stats=False,
            elapsed=False,
        ) as bar:
            processed_files = []
            for i, item in enumerate(download_queue):
                task = item["task"]
                bar.text = f"-> [Tag: {task['name'][:15]}]"

                self._sync_file(item["src"], item["dest"], task)
                processed_files.append(
                    (str(item["src"]), str(item["dest"]), item["soc_name"])
                )

                check_soc = ( i == len(download_queue) - 1 ) or ( download_queue[i + 1]["soc_name"] != item["soc_name"] )
                if check_soc:
                    self.post_process_task(task, item["save_dir"], processed_files)
                    processed_files = []
                bar()

        ui.print_status("所有同步任务已完成！")
