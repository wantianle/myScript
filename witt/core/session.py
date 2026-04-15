from core.context import TaskContext
from core.runner import ScriptRunner
from core.adapter.docker import DockerAdapter
from core.adapter.ssh import SSHAdapter
from core.engine.downloader import RecordDownloader
from core.engine.player import RecordPlayer
from core.engine.recorder import Recorder
from core.repository import LibraryCacheRepository, MetadataRepository
from core.adapter.base import BaseAdapter

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = BASE_DIR / "config" / "settings.yaml"


class AppSession:
    """初始化并持有所有执行对象，减少重复创建"""

    def __init__(self) -> None:
        self.ctx = TaskContext(DEFAULT_CONFIG_PATH)
        self.runner = ScriptRunner(self.ctx)
        self.recorder = Recorder(self)
        self.metadata_repository = MetadataRepository()
        self.library_cache_repository = LibraryCacheRepository(
            self.ctx.work_dir / ".witt" / "local_library.json"
        )
        self.record_downloader = RecordDownloader(
            self,
            metadata_repository=self.metadata_repository,
        )
        self.player = RecordPlayer(
            self,
            library_cache=self.library_cache_repository,
            metadata_repository=self.metadata_repository,
        )

    @property
    def executor(self) -> BaseAdapter:
        return (
            DockerAdapter(self.ctx)
            if self.ctx.logic.mode != 3
            else SSHAdapter(self.ctx)
        )

    def init_logging(self) -> None:
        self.ctx.setup_logger()
