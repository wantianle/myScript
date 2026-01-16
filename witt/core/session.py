import logging
from core.context import TaskContext
from core.adapter.docker import DockerAdapter
from core.engine.recorder import Recorder
from core.adapter.ssh import SSHAdapter
from core.runner import ScriptRunner
from core.engine.player import RecordPlayer
from core.engine.dowloader import RecordDownloader
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = BASE_DIR / "config" / "settings.yaml"


class AppSession:
    """初始化并持有所有执行对象，减少重复创建"""

    def __init__(self):
        self.ctx = TaskContext(DEFAULT_CONFIG_PATH)
        self.ctx.setup_logger()
        self.runner = ScriptRunner(self.ctx)
        self.recorder = Recorder(self)
        self.downloader = RecordDownloader(self)
        self.player = RecordPlayer(self)

    @property
    def executor(self):
        return (
            DockerAdapter(self.ctx)
            if self.ctx.config["logic"].get("mode") != 3
            else SSHAdapter(self.ctx.config)
        )

    def record_query(self):
        self.runner.run_find_record()

    def record_compress(self, record_path: Path, blacklist:list):
        """Channel 过滤压缩"""
        self.ctx.config["logic"]["blacklist"] = blacklist
        logging.info(f">>> 执行数据压缩，删除 channels {len(blacklist)} 个")
        return self.record_slice(record_path)

    def record_slice(self, input_path: Path, tag_dt=None):
        """时间截取切片"""
        tag_start, tag_end = None, None
        if tag_dt:
            tag_start = tag_dt - timedelta(seconds=self.ctx.config["logic"]["before"])
            tag_end = tag_dt + timedelta(seconds=self.ctx.config["logic"]["after"])
        return self.recorder.split(
            host_in=str(input_path),
            host_out=str(input_path.with_suffix(".split")),
            start_dt=tag_start,
            end_dt=tag_end,
            blacklist=self.ctx.config["logic"]["blacklist"],
        )

    def record_split(self, selected_list):
        self.downloader.download_record(selected_list)

    def restore_env(self):
        self.runner.run_restore_env()

    def task_play(self, records, start=0, end=0, selected_channels=None):
        self.player.play(records, start, end, selected_channels)
