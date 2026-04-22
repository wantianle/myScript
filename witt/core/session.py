import shutil
from pathlib import Path
from typing import Optional, Union

from core.adapter.docker import DockerAdapter
from core.adapter.ssh import SSHAdapter
from core.context import TaskContext
from core.engine.downloader import RecordDownloader
from core.engine.player import RecordPlayer
from core.engine.recorder import Recorder
from core.repository import (
    LibraryCacheRepository,
    MetadataRepository,
    ReplayHistoryRepository,
)
from core.runner import RuntimeCoordinator

DEFAULT_CONFIG_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "settings.yaml"
)


def ensure_user_config_path(
    template_path: Path = DEFAULT_CONFIG_TEMPLATE_PATH,
    user_home: Optional[Path] = None,
) -> Path:
    """确保用户配置文件存在，不存在时从仓库模板复制。"""
    config_home = Path(user_home) if user_home is not None else Path.home()
    config_dir = config_home / ".witt"
    config_path = config_dir / "settings.yaml"
    if config_path.exists():
        return config_path
    config_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(template_path), str(config_path))
    return config_path


class AppSession:
    """初始化并持有所有执行对象，减少重复创建"""

    def __init__(self, config_path: Optional[Path] = None) -> None:
        config_path = (
            Path(config_path)
            if config_path is not None
            else ensure_user_config_path()
        )
        self.ctx = TaskContext(config_path)
        self.runtime = RuntimeCoordinator(self.ctx)
        self.recorder = Recorder(self)
        self.metadata_repository = MetadataRepository()
        library_cache_path = self.ctx.work_dir / ".witt" / "local_library.json"
        replay_history_path = config_path.parent / "replay_history.json"
        self.library_cache_repository = LibraryCacheRepository(library_cache_path)
        self.replay_history_repository = ReplayHistoryRepository(replay_history_path)
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
    def source_executor(self) -> Union[DockerAdapter, SSHAdapter]:
        return (
            DockerAdapter(self.ctx)
            if self.ctx.logic.mode != 3
            else SSHAdapter(self.ctx)
        )

    @property
    def playback_executor(self) -> DockerAdapter:
        """回播相关命令始终在本地 Docker 环境执行。"""
        return DockerAdapter(self.ctx)

    @property
    def executor(self) -> Union[DockerAdapter, SSHAdapter]:
        """兼容旧调用，默认返回查询/切片阶段的数据源执行器。"""
        return self.source_executor
