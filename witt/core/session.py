from core.context import TaskContext
from core.runner import ScriptRunner
from core.adapter.docker import DockerAdapter
from core.adapter.ssh import SSHAdapter
from core.engine.dowloader import RecordDownloader
from core.engine.player import RecordPlayer
from core.engine.recorder import Recorder

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
