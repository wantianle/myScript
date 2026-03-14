import logging
import json
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

    @property
    def mode(self):
        return self.ctx.config["logic"]["mode"]

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

    def _save_contract(self, task, save_dir, file_infos):
        """保存元数据，实现数据信息缓存，减少底层重复计算，并为回播提供必要的上下文信息"""
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

    def _post_process_task(self, task, save_dir, file_infos):
        """生成元数据、README 和 version"""
        # 生成元数据文件
        self._save_contract(task, save_dir, file_infos)
        # 同步 version
        src_dir = Path(file_infos[0][0]).parent
        if self.mode == 3:
            find_cmd = f"ls {src_dir}/version* 2>/dev/null || true"
            try:
                result_str = self.session.executor.execute(find_cmd).strip()
                if result_str:
                    # 获取远程文件列表（处理可能存在的多个版本文件）
                    remote_version_files = result_str.split()
                    for remote_v_path in remote_version_files:
                        v_name = Path(remote_v_path).name
                        v_dest = save_dir / v_name
                        self.session.executor.fetch_file(remote_v_path, v_dest)
                        logging.info(f"[SYNC_VERSION] 成功同步远程文件: {v_name}")
                else:
                    logging.warning(
                        f"[SYNC_VERSION] 远程目录未发现任何 version* 文件: {src_dir}"
                    )
            except Exception as e:
                logging.debug(f"远程版本文件检测发生异常: {e}")
        else:
            # 本地/NAS 模式：可以使用 glob
            for v_src in src_dir.glob("version*"):
                v_dest = save_dir / v_src.name
                shutil.copy2(v_src, v_dest)

        # 生成 README
        if not v_dest.exists():
            logging.warning(
                f"[SYNC_VERSION] {src_dir} 未找到 version 文件，影响回播的版本同步！"
            )
        else:
            v_content = v_dest.read_text() if v_dest.exists() else "N/A"
        nas_path = save_dir.relative_to(Path(self.ctx.config["host"]["dest_root"]))
        before = int(self.ctx.config["logic"]["before"])
        after = int(self.ctx.config["logic"]["after"])
        play_start = (before - 15) if (before - 15) > 0 else 0
        records_str = " ".join([Path(f[1]).name for f in file_infos])
        readme_content = f"""- **tag：** {task["time"]} {task["name"]} duration: {before + after}s
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
cd {self.ctx.config["host"]["nas_root"]}/{nas_path}
```
- **数据时刻：**
```bash
cyber_recorder play -s {play_start} -f {records_str}
```
"""
        readme_path = save_dir / "README.md"
        readme_path.write_text(readme_content, encoding="utf-8")
        logging.info(f"[TASK_COMPLETE] Tag: {task['name']} | Saved to: {save_dir}")
        logging.info(f"  Files: {[Path(f[1]).name for f in file_infos]}")

    def _sync_file(self, src, dest, task):
        """生成 .split 文件，全量覆盖，最后清理中间文件"""
        logic = self.ctx.config["logic"]
        tag_dt = parser.str_to_time(task["time"])
        t_start = tag_dt - timedelta(seconds=int(logic["before"]))
        t_end = tag_dt + timedelta(seconds=int(logic["after"]))
        blacklist = logic.get("blacklist")
        if blacklist:
            logging.info(f"[RECORDER_COMPRESS] Blacklist: {','.join(blacklist)}")
        if self.ctx.config["logic"]["mode"] != 3:
            self.session.recorder.split(src, dest, t_start, t_end, blacklist)
        else:
            remote_out = f"{src}.split"
            self.session.executor.remove(remote_out)
            self.session.recorder.split(src, remote_out, t_start, t_end, blacklist)
            self.session.executor.fetch_file(remote_out, dest)
            self.session.executor.remove(remote_out)

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
                save_dir = self.ctx.get_task_dir(task["id"], task["name"], soc_name)
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
                is_last_in_queue = i == len(download_queue) - 1

                if is_last_in_queue:
                    should_post_process = True
                else:
                    next_item = download_queue[i + 1]
                    should_post_process = (next_item["task"]["id"] != task["id"]) or (
                        next_item["soc_name"] != item["soc_name"]
                    )

                if should_post_process:
                    self._post_process_task(task, item["save_dir"], processed_files)
                    processed_files = []
                bar()

        ui.print_status("所有同步任务已完成！")
