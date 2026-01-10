import os
import time
import json
import subprocess
import shutil
import logging
from utils import handles
from datetime import datetime, timedelta
from pathlib import Path
from typing import List


class RecordDownloader:
    def __init__(self, ctx):
        self.ctx = ctx
        self.config = self.ctx.config
        self.dest_root = Path(self.config["host"]["dest_root"])
        self.mode = self.config["env"].get("mode", 1)
        self.remote_user = self.config["remote"]["user"]
        self.remote_ip = self.config["remote"]["ip"]

    def _get_file_size(self, path: str) -> int:
        """获取文件大小（本地或远程）"""
        if self.mode == 3:
            cmd = f"ssh {self.remote_user}@{self.remote_ip} 'stat -c %s {path}'"
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            return int(res.stdout.strip()) if res.returncode == 0 else 0
        else:
            p = Path(path)
            return p.stat().st_size if p.exists() else 0

    def _cleanup_extra_files(self, save_dir: Path, expected_filenames: List[str]):
        """
        清理目标目录中不属于当前任务的文件
        """
        # 这里的 expected_filenames 是当前清单里的文件名列表
        # 加上我们必须保留的元数据文件
        whitelist = set(expected_filenames) | {"version.json", "README.md"}

        for item in save_dir.iterdir():
            if item.is_file() and item.name not in whitelist:
                # print(f"[Cleanup] 清理多余文件: {item.name}")
                item.unlink()

    def _cleanup_source_file(self, source_path: str):
        """
        删除源端的中间文件
        """
        try:
            if self.mode == 3:
                rm_cmd = (
                    f"ssh {self.remote_user}@{self.remote_ip} 'rm -f {source_path}'"
                )
                subprocess.run(rm_cmd, shell=True, capture_output=True)
                # logging.info(f"[Remote Cleanup] 已删除源端中间文件: {Path(source_path).name}")
            else:
                p = Path(source_path)
                if p.exists():
                    p.unlink()
                    # logging.info(f"[Local Cleanup] 已删除源端中间文件: {p.name}")
        except Exception as e:
            logging.warning(f"清理源端文件失败: {source_path}, 错误: {e}")

    def _save_contract(self, task, save_dir, file_infos):
        """保存元数据，实现信息透传"""
        tag_dir = save_dir.parent
        meta_path = tag_dir / "meta.json"

        dt_tag = handles.str_to_time(task["time"])
        bf, af = int(self.config["logic"]["before"]), int(
            self.config["logic"]["after"]
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
        # logging.info(f">>> 元数据文件已更新: {meta_path.name}")

    def _post_process_task(self, task, save_dir, file_infos):
        """生成元数据文件、 README 和 version.json"""
        self._save_contract(task, save_dir, file_infos)

        # 同步 version.json
        src_dir = os.path.dirname(file_infos[0][0])
        v_src = f"{src_dir}/version.json"
        v_dest = save_dir / "version.json"

        try:
            if self.mode == 3:
                subprocess.run(
                    [
                        "rsync",
                        "-a",
                        f"{self.remote_user}@{self.remote_ip}:{v_src}",
                        str(v_dest),
                    ],
                    capture_output=True,
                )
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

    def download_tasks(self):
        """核心下载逻辑"""
        from alive_progress import alive_bar
        # 预检与计算总大小
        print(">>> 正在预检磁盘空间...")
        total_bytes = 0
        task_details = []
        files_to_cleanup = set()
        for task in handles.parse_manifest(self.ctx.manifest_path):
            task_size = 0
            file_infos = []
            for f in task["files"]:
                split_file = f"{f}.split"
                size = self._get_file_size(split_file)
                task_size += size
                file_infos.append((split_file, size))
            total_bytes += task_size
            task_details.append((task, task_size, file_infos))

        # 检查本地空间
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

            for task, task_size, file_infos in task_details:
                folder_name = (
                    f"{int(task['id']):02d}_{handles.sanitize_name(task['name'])}"
                )
                save_dir = (
                    self.dest_root
                    / self.ctx.target_date[:8]
                    / self.ctx.vehicle
                    / folder_name
                    / self.config["logic"]["soc"]
                )
                save_dir.mkdir(parents=True, exist_ok=True)

                filenames = [Path(f[0]).name for f in file_infos]
                self._cleanup_extra_files(save_dir, filenames)

                for src_path, f_size in file_infos:
                    dest_file = save_dir / Path(src_path).name

                    # 检查断点续传
                    if dest_file.exists() and dest_file.stat().st_size == f_size:
                        processed_bytes += f_size
                        bar(processed_bytes / total_bytes)
                        continue

                    # 启动拷贝进程
                    cmd = (
                        [
                            "scp",
                            "-q",
                            f"{self.remote_user}@{self.remote_ip}:{src_path}",
                            str(dest_file),
                        ]
                        if self.mode == 3
                        else ["cp", src_path, str(dest_file)]
                    )

                    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True)
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
                self._post_process_task(task, save_dir, file_infos)
        if files_to_cleanup:
            for f in files_to_cleanup:
                self._cleanup_source_file(f)
