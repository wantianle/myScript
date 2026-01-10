import logging
from core.context import TaskContext
from core.docker_adapter import DockerAdapter
from core.record_manager import RecordManager
from core.ssh_adapter import SSHAdapter
from core.task_executor import TaskExecutor
from core.player import RecordPlayer
from core.dowload_record import RecordDownloader
from datetime import timedelta
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = BASE_DIR / "config" / "settings.yaml"

class AppSession:
    """初始化并持有所有执行对象，减少重复创建"""

    def __init__(self):
        self.ctx = TaskContext(DEFAULT_CONFIG_PATH)
        self.config = self.ctx.config
        if self.config["env"].get("mode") == 3:
            self.backend = SSHAdapter(self.ctx)
        else:
            self.backend = DockerAdapter(self.ctx)
        self.record_mgr = RecordManager(self.backend)
        self.executor = TaskExecutor(self.ctx)
        self.player = RecordPlayer(self)

    def task_query(self):
        self.ctx.setup_logger()
        logging.info(">>> 执行数据检索与同步 (find_record)...")
        self.executor.run_find_record()

    def task_compress(self, record_path: Path):
        """Channel 过滤压缩"""
        self.ctx.setup_logger()
        info = self.record_mgr.get_info(str(record_path))
        channels = info.get("channels", [])
        if not channels:
            logging.warning("未发现有效 Channel，跳过压缩")
            return
        print(f"\n>>> 分析文件: {record_path.name}")
        print(f"bgin: {info.get('begin_time')}   end: {info.get('end_time')}")
        print("-" * 72)
        print(f"{'ID':<4} | {'Channel Name':<55} | {'Messages'}")
        print("-" * 72)
        for i, ch in enumerate(channels, 1):
            print(f"{i:<4} | {ch['name']:<55} | {ch['count']}")

        user_in = input(
            "\n[操作]: 回车跳过 | '0'全删 | 序号(如1,3,20-28)删除指定 channel: "
        ).strip()
        if not user_in:
            return

        to_delete = [c["name"] for c in channels] if user_in == "0" else []
        if not to_delete:
            indices = []
            for part in user_in.split(","):
                try:
                    if "-" in part.strip():
                        start_str, end_str = part.split("-")
                        start, end = int(start_str), int(end_str)
                        indices.extend(range(start - 1, end))
                    else:
                        indices.append(int(part) - 1)
                except ValueError:
                    print(f"输入无效 {part}")
                    return
            indices = sorted(list(set(indices)))
            to_delete = [channels[i]["name"] for i in indices if 0 <= i < len(channels)]
        new_blacklist = list(
            set(self.config["logic"].get("blacklist") or [] + to_delete)
        )
        self.config["logic"]["blacklist"] = new_blacklist
        logging.info(f">>> 执行数据压缩: {new_blacklist}")

    def task_slice(self, input_path: Path, tag_dt=None):
        """时间截取切片"""
        self.ctx.setup_logger()
        before = self.config["logic"]["before"]
        after = self.config["logic"]["after"]
        tag_start, tag_end = None, None
        if tag_dt:
            tag_start = tag_dt - timedelta(seconds=before)
            tag_end = tag_dt + timedelta(seconds=after)
        success = self.record_mgr.split(
            host_in=str(input_path),
            # host_out=str(input_path.with_suffix(".split")),
            start_dt=tag_start,
            end_dt=tag_end,
            blacklist=self.config["logic"]["blacklist"],
        )

        if not success:
            logging.warning(f">>> [Skip] 文件 {input_path} 可能已损坏，已自动跳过。")

    def task_download(self):
        """
        读取清单 -> 用户选择 -> 执行下载
        """
        downloader = RecordDownloader(self.ctx)
        downloader.download_tasks()

    def task_sync(self):
        """
        同步环境
        """
        self.executor.run_restore_env()
