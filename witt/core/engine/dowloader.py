import logging
import json
import os
import shutil
import subprocess
from alive_progress import alive_bar

# from core.session import AppSession
from datetime import datetime, timedelta
from pathlib import Path
from utils import handles


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

    def save_contract(self, task, save_dir, file_infos):
        """保存元数据，实现信息透传"""
        tag_dir = save_dir.parent
        meta_path = tag_dir / "meta.json"

        dt_tag = handles.str_to_time(task["time"])
        bf, af = int(self.ctx.config["logic"]["before"]), int(
            self.ctx.config["logic"]["after"]
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
            except:
                logging.warning("元数据文件损坏，执行全量重写")
        current_soc = self.ctx.config["logic"]["soc"]
        contract["files"][current_soc] = [Path(f[1]).name for f in file_infos]
        contract["last_update"][current_soc] = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        meta_path.write_text(json.dumps(contract, indent=4, ensure_ascii=False))

    def post_process_task(self, task, save_dir, file_infos):
        """生成元数据文件、 README 和 version.json"""
        self.save_contract(task, save_dir, file_infos)

        # 同步 version.json
        src_dir = Path(file_infos[0][0]).parent
        v_src = src_dir / "version.json"
        v_dest = save_dir / "version.json"

        try:
            if self.mode == 3:
                remote_src = f"{self.remote_user}@{self.remote_ip}:{v_src}"
                down_cmd = ["scp", "-q", "-o", remote_src, v_dest]

                env_c = os.environ.copy()
                env_c["LC_ALL"] = "C"

                result = subprocess.run(
                    down_cmd, env=env_c, capture_output=True, text=True
                )

                if result.returncode != 0:
                    print(f"拷贝失败: {result.stderr}")
            else:
                if os.path.exists(v_src):
                    shutil.copy2(v_src, v_dest)
        except Exception as e:
            logging.warning(f"拷贝 {task['name']}: version.json 文件失败：{e}")

        # 生成 README
        v_content = v_dest.read_text() if v_dest.exists() else "N/A"
        records_str = " ".join([Path(f[1]).name for f in file_infos])
        readme_content = f"""- **tag：** {task['time']} {task['name']}
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
{self.ctx.config['host']['nas_root']}/{self.ctx.target_date}/{self.ctx.vehicle}/{task['name']}/{self.ctx.config['logic']['soc']}
```
- **数据时刻：**
```bash
{records_str}
```
- **回播命令：**
```bash
cd {save_dir}
cyber_recorder play -l -f {records_str}
```
"""
        readme_path = save_dir / "README.md"
        readme_path.write_text(readme_content, encoding="utf-8")

        logging.info(f"[TASK_COMPLETE] Tag: {task['name']} | Saved to: {save_dir}")
        logging.debug(f"    Files: {[f[1] for f in file_infos]}")

    def _sync_file(self, src, dest, task):
        """
        同步的核心逻辑：
        1. 在执行环境生成 .split 文件
        2. 如果是远程，拉回宿主机
        3. 清理中间文件
        """
        # 环境准备

        logic = self.ctx.config["logic"]
        tag_dt = handles.str_to_time(task["time"])
        t_start = tag_dt - timedelta(seconds=int(logic["before"]))
        t_end = tag_dt + timedelta(seconds=int(logic["after"]))
        blacklist = logic.get("blacklist")

        if self.ctx.config["logic"]["mode"] != 3:
            self.session.recorder.split(
                host_in=src,
                host_out=dest,
                start_dt=t_start,
                end_dt=t_end,
                blacklist=blacklist,
            )
        else:
            remote_out = f"{src}.split"
            self.session.executor.remove(remote_out)
            success = self.session.recorder.split(
                host_in=src,
                host_out=remote_out,
                start_dt=t_start,
                end_dt=t_end,
                blacklist=blacklist,
            )

            if success:
                self.session.executor.fetch_file(remote_out, dest)
                self.session.executor.remove(remote_out)
            else:
                logging.error(f"切片生成失败: {src}")

    def _get_task_save_dir(self, task) -> Path:
        """统一管理保存路径规则"""
        return self.ctx.get_task_dir(
            task["id"], task["name"], self.ctx.config["logic"]["soc"]
        )

    def download_record(self, task_list):
        """
        主入口：现在它只负责高层调度和进度条
        """
        # 任务打平 (只处理有路径的任务)
        download_queue = []
        prepared_dirs = set()
        for task in task_list:
            if not task["paths"]:
                continue
            save_dir = self._get_task_save_dir(task)
            if save_dir not in prepared_dirs:
                self._prepare_dir(save_dir)
                prepared_dirs.add(save_dir)
            save_dir.mkdir(parents=True, exist_ok=True)
            for p in task["paths"]:
                download_queue.append(
                    {
                        "src": Path(p),
                        "dest": save_dir / (Path(p).name + ".split"),
                        "task": task,
                        "save_dir": save_dir,
                    }
                )

        if not download_queue:
            logging.warning("下载队列为空")
            return

        print(f"\n>>> 准备同步 {len(download_queue)} 个 Record 片段...")

        # 执行下载流水线
        with alive_bar(
            len(download_queue),
            title="Progress",
            theme="classic",
            stats=False,
            elapsed=False,
        ) as bar:
            processed_files = []  # 记录当前任务已完成的文件，用于后处理

            for i, item in enumerate(download_queue):
                task = item["task"]
                bar.text = f"-> [Tag: {task['name'][:15]}]"

                # 执行单个文件同步
                self._sync_file(item["src"], item["dest"], task)
                processed_files.append((str(item["src"]), str(item["dest"])))

                # 判断是否是当前 Tag 的最后一个文件，或者是整个队列的最后一个
                is_last_in_tag = (i == len(download_queue) - 1) or (
                    download_queue[i + 1]["task"]["id"] != task["id"]
                )

                if is_last_in_tag:
                    self.post_process_task(task, item["save_dir"], processed_files)
                    processed_files = []

                bar()

        print("\n>>> 所有同步任务已完成！")
