import logging
import os
import yaml
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from core.models import AppConfig, DockerConfig, HostConfig, LogicConfig, PathsConfig, RemoteConfig

class Formatter(logging.Formatter):
    """处理颜色与格式"""

    COLORS = {
        "DEBUG": "\033[0;90m",
        "INFO": "\033[0;32m",
        "WARNING": "\033[0;33m",
        "ERROR": "\033[0;31m",
        "RESET": "\033[0m",
    }

    def format(self, record) -> str:
        color = self.COLORS.get(record.levelname, self.COLORS["RESET"])
        fmt = f"{color}[%(levelname)s] %(message)s{self.COLORS['RESET']}"
        return logging.Formatter(fmt).format(record)


@dataclass
class TaskContext:
    _logger_ready = False
    config_path: Path

    app_config: AppConfig = field(init=False)
    playback_blacklist: List[str] = field(init=False, default_factory=list)
    active_log_key: str = field(init=False, default="")

    def __post_init__(self):
        """加载配置并初始化当前会话的上下文目录。"""
        raw_config = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))
        self.app_config = AppConfig.from_dict(raw_config)
        self.logic.target_date = datetime.now().strftime("%Y%m%d")

    @property
    def host(self) -> HostConfig:
        return self.app_config.host

    @property
    def remote(self) -> RemoteConfig:
        return self.app_config.remote

    @property
    def docker(self) -> DockerConfig:
        return self.app_config.docker

    @property
    def paths(self) -> PathsConfig:
        return self.app_config.paths

    @property
    def logic(self) -> LogicConfig:
        return self.app_config.logic

    @property
    def vehicle(self) -> str:
        return self.logic.vehicle

    @property
    def target_date(self) -> str:
        return self.logic.target_date

    @property
    def work_dir(self) -> Path:
        base = Path(self.host.dest_root)
        return base / self.target_date[:8] / self.vehicle

    @property
    def log_dir(self) -> Path:
        return self.work_dir / ".witt" / "log"

    def get_task_dir(self, task_id: str, task_time: str, soc: str = "") -> Path:
        """统一管理任务存储路径规则，目录名使用 ASCII 时间戳"""
        dt = datetime.strptime(task_time, "%Y-%m-%d %H:%M:%S")
        folder = f"{int(task_id):02d}.{dt.strftime('%Y%m%d_%H%M%S')}"
        path = self.work_dir / folder
        if soc:
            path = path / soc
        return path

    def setup_logger(self) -> None:
        """初始化全局日志器。"""
        current_log_key = "{0}:{1}".format(self.target_date, self.vehicle)
        if self._logger_ready and self.active_log_key == current_log_key:
            return
        self.log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = self.log_dir / f"witt_{timestamp}.log"

        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)

        if logger.hasHandlers():
            for handler in list(logger.handlers):
                handler.close()
                logger.removeHandler(handler)

        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

        sh = logging.StreamHandler()
        sh.setFormatter(Formatter())
        sh.setLevel(logging.WARNING)
        logger.addHandler(sh)

        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(formatter)
        fh.setLevel(logging.DEBUG)
        logger.addHandler(fh)
        TaskContext._logger_ready = True
        self.active_log_key = current_log_key
        logging.info("=" * 50)
        logging.info(
            "Witt Logger Initialized. Data_root: %s", self.host.data_root
        )
        logging.info("Log File: %s", log_file)
        logging.info("=" * 50)

    def get_library_fingerprint(self) -> str:
        """
        检查工作目录下所有子目录的最新修改时间，生成指纹。
        """
        if not self.work_dir.exists():
            return ""
        mtimes = [
            path.stat().st_mtime for path in self.work_dir.rglob("*") if path.is_dir()
        ]
        mtimes.append(self.work_dir.stat().st_mtime)
        latest_mtime = max(mtimes)
        return f"{datetime.now().day}_{latest_mtime}"

    def get_env_vars(self) -> Dict[str, str]:
        """构建注入 Shell 脚本的环境变量字典"""
        vars = {
            "VEHICLE": self.vehicle,
            "TARGET_DATE": self.target_date,
            "NAS_ROOT": self.host.nas_root,
            "DEST_ROOT": self.host.dest_root,
            "MDRIVE_ROOT": self.host.mdrive_root,
            "DATA_ROOT": self.host.data_root,
            "SOC": self.logic.soc,
            "BEFORE": self.logic.before,
            "AFTER": self.logic.after,
            "MODE": self.logic.mode,
            "VERSION": self.logic.version,
            "CONTAINER": self.docker.container,
            "REMOTE_USER": self.remote.user,
            "REMOTE_IP": self.remote.ip,
            "REMOTE_DATA_ROOT": self.remote.data_root,
        }
        full_env = os.environ.copy()
        full_env.update({k: str(v) for k, v in vars.items()})
        return full_env
