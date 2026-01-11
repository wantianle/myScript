import logging
import json
import os
import shutil
import subprocess
import time
from alive_progress import alive_bar
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional
from utils import handles


class RecordDownloader:
    def __init__(self, session):
        self.ctx = session.ctx
        self.config = self.ctx.config
        self.dest_root = Path(self.config["host"]["dest_root"])
        self.mode = self.config["env"].get("mode", 1)
        self.remote_user = self.config["remote"]["user"]
        self.remote_ip = self.config["remote"]["ip"]

    def get_file_size(self, path: str) -> int:
        """获取文件大小（本地或远程）"""
        if self.mode == 3:
            stat_cmd = f"ssh {self.remote_user}@{self.remote_ip} 'stat -c %s {path}'"
            res = subprocess.run(stat_cmd, shell=True, capture_output=True, text=True)
            return int(res.stdout.strip()) if res.returncode == 0 else 0
        else:
            p = Path(path)
            return p.stat().st_size if p.exists() else 0

    def cleanup_file(self, target_path: Path, file_list: Optional[List[str]] = None):
        """
        删除源端的中间文件
        """
        if file_list:
            whitelist = set(file_list) | {"version.json", "README.md"}
            for item in target_path.iterdir():
                if item.is_file() and item.name not in whitelist:
                    item.unlink()
        else:
            try:
                if self.mode == 3:
                    rm_cmd = (
                        f"ssh {self.remote_user}@{self.remote_ip} 'rm -f {target_path}'"
                    )
                    subprocess.run(rm_cmd, shell=True, capture_output=True)
                else:
                    p = Path(target_path)
                    if p.exists():
                        p.unlink()
            except Exception as e:
                logging.warning(f"清理源端文件失败: {target_path}, 错误: {e}")

    def save_contract(self, task, save_dir, file_infos):
        """保存元数据，实现信息透传"""
        tag_dir = save_dir.parent
        meta_path = tag_dir / "meta.json"

        dt_tag = handles.str_to_time(task["time"])
        bf, af = int(self.config["logic"]["before"]), int(self.config["logic"]["after"])

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
            "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "files": {},
        }
        if meta_path.exists():
            try:
                old_contract = json.loads(meta_path.read_text(encoding="utf-8"))
                contract["files"] = old_contract.get("files", {})
            except:
                logging.warning("元数据文件损坏，执行全量重写")
        current_soc = self.ctx.config["logic"]["soc"]
        contract["files"][current_soc] = [Path(f[0]).name for f in file_infos]
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
                down_cmd = f"rsync -a {self.remote_user}@{self.remote_ip}:{v_src} {v_dest}"
                subprocess.run(down_cmd, shell=True, capture_output=True)
            else:
                if os.path.exists(v_src):
                    shutil.copy2(v_src, v_dest)
        except:
            pass

        # 生成 README
        v_content = v_dest.read_text() if v_dest.exists() else "N/A"
        records_str = " ".join([Path(f[0]).name for f in file_infos])
        readme_content = f"""- **tag：** {task['time']} {task['name']}
- **问题描述：**
> 填写补充描述
- **预期结果：**
> 填写正确情况
- **实际结果：**
> 填写错误情况
- **车辆软硬件信息：**
```json
{v_content}
```
- **数据路径：**
```bash
{self.config['host']['nas_root']}/{self.ctx.target_date}/{self.ctx.vehicle}/{task['name']}/{self.config['logic']['soc']}
```
- **数据时刻：**
```bash
{records_str}
```
"""
        readme_path = save_dir / "README.md"
        readme_path.write_text(readme_content, encoding="utf-8")

    def download_record(self, task_list):
        """核心下载逻辑"""
        total_bytes = 0
        task_infos = []
        files_to_cleanup = set()
        for task in task_list:
            task_size = 0
            file_infos = []
            if not task["paths"]: continue
            for f in task["paths"]:
                split_file = f"{f}.split"
                size = self.get_file_size(split_file)
                task_size += size
                file_infos.append((split_file, size))
            total_bytes += task_size
            task_infos.append((task, task_size, file_infos))

        print(">>> 正在预检磁盘空间...")
        usage = shutil.disk_usage(self.dest_root)
        if total_bytes > (usage.free - 1024 * 1024 * 100):
            print(
                f"错误: 磁盘空间不足！需要 {total_bytes/1e9:.2f}GB, 剩余 {usage.free/1e9:.2f}GB"
            )
            return

        print(f"计划同步数据量: {total_bytes/1e6:.2f} MB")

        # 执行下载
        with alive_bar(
            total_bytes, title="Overall", manual=True, unit="B", scale="IEC"
        ) as bar:
            processed_bytes = 0

            for task, task_size, file_infos in task_infos:
                folder_name = f"{int(task['id']):02d}.{task['name']}"
                soc_name = self.config["logic"]["soc"].strip("/")
                save_dir = (
                    self.dest_root
                    / self.ctx.target_date[:8]
                    / self.ctx.vehicle
                    / folder_name
                    / soc_name
                )
                save_dir.mkdir(parents=True, exist_ok=True)

                filenames = [Path(f[0]).name for f in file_infos]
                self.cleanup_file(save_dir, filenames)

                for src_path, f_size in file_infos:
                    dest_file = save_dir / Path(src_path).name

                    # 检查断点续传
                    if dest_file.exists() and dest_file.stat().st_size == f_size:
                        processed_bytes += f_size
                        bar(processed_bytes / total_bytes)
                        continue

                    cp_cmd = (
                        f"scp -q f {self.remote_user}@{self.remote_ip}:{src_path} {dest_file}"
                        if self.mode == 3
                        else f"cp {src_path} {dest_file}"
                    )
                    proc = subprocess.Popen(
                        cp_cmd, shell=True, stderr=subprocess.PIPE, text=True
                    )
                    # 监控进度
                    while proc.poll() is None:
                        current_f = (
                            dest_file.stat().st_size if dest_file.exists() else 0
                        )
                        overall_ratio = (processed_bytes + current_f) / total_bytes
                        bar(min(overall_ratio, 1.0))
                        bar.text = f"-> Copying: {folder_name[:15]}.. | {dest_file.name[-15:]} ({(current_f/(1024*1024)):.1f}MB)"
                        time.sleep(0.2)
                    processed_bytes += f_size
                    bar(min(processed_bytes / total_bytes, 1.0))
                    exit_code = proc.wait()
                    if exit_code != 0:
                        _, stderr = proc.communicate()
                        logging.warning(f"拷贝失败: {src_path}\n >>> {stderr}")
                    else:
                        if Path(src_path).name.endswith((".split", ".sliced")):
                            files_to_cleanup.add(src_path)
                self.post_process_task(task, save_dir, file_infos)
        if files_to_cleanup:
            logging.info("正在清理源端 split 文件...")
            for f in files_to_cleanup:
                self.cleanup_file(f)
