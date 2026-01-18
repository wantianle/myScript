import atexit
import logging
import os
import tempfile
import shutil
import yaml
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict

from utils import parser


class Formatter(logging.Formatter):
    """处理颜色与格式"""

    COLORS = {
        "DEBUG": "\033[0;90m",
        "INFO": "\033[0;32m",
        "WARNING": "\033[0;33m",
        "ERROR": "\033[0;31m",
        "RESET": "\033[0m",
    }

    def format(self, record):
        color = self.COLORS.get(record.levelname, self.COLORS["RESET"])
        fmt = f"{color}[%(levelname)s] %(message)s{self.COLORS['RESET']}"
        return logging.Formatter(fmt).format(record)


@dataclass
class TaskContext:
    config_path: Path

    config: dict = field(init=False)
    temp_dir: Path = field(init=False)
    _logger_ready: bool = field(default=False, init=False)

    def __post_init__(self):
        self.config = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))
        self.config["logic"]["target_date"] = datetime.now().strftime("%Y%m%d")
        self.temp_dir = Path(tempfile.mkdtemp(prefix="witt_session_"))
        atexit.register(self._cleanup_temp)

    @property
    def vehicle(self):
        return self.config["logic"]["vehicle"]

    @property
    def target_date(self):
        return self.config["logic"]["target_date"]

    @property
    def work_dir(self) -> Path:
        base = Path(self.config["host"]["dest_root"])
        return base / self.target_date[:8] / self.vehicle

    @property
    def log_dir(self) -> Path:
        return self.work_dir / ".witt" / "log"

    @property
    def manifest_path(self) -> Path:
        return self.temp_dir / "tasks.list"

    def _cleanup_temp(self) -> None:
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def get_task_dir(self, task_id: str, task_name: str, soc: str = "") -> Path:
        """统一管理任务存储路径规则"""
        folder = f"{int(task_id):02d}.{task_name}"
        path = self.work_dir / folder
        if soc:
            path = path / soc
        return path

    def setup_logger(self) -> None:
        """
        写日志时才创建文件。
        """
        if self._logger_ready:
            return
        self.log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = self.log_dir / f"witt_{timestamp}.log"

        logger = logging.getLogger()
        logger.setLevel(logging.INFO)

        # if logger.hasHandlers():
        #     logger.handlers.clear()

        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

        sh = logging.StreamHandler()
        sh.setFormatter(Formatter())
        sh.setLevel(logging.WARNING)
        logger.addHandler(sh)

        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(formatter)
        fh.setLevel(logging.INFO)
        logger.addHandler(fh)

        self._logger_ready = True

    def get_library_fingerprint(self) -> str:
        """
        如果在这个目录下下载了新文件，work_dir 的 mtime 必变
        """
        if not self.work_dir.exists():
            return ""
        return f"{datetime.now().day}_{self.work_dir.stat().st_mtime}"

    def get_env_vars(self) -> Dict[str, str]:
        """构建注入 Shell 脚本的环境变量字典"""
        vars = {
            "MANIFEST_PATH": self.manifest_path,
            "VEHICLE": self.vehicle,
            "TARGET_DATE": self.target_date,
            "NAS_ROOT": self.config["host"]["nas_root"],
            "DEST_ROOT": self.config["host"]["dest_root"],
            "MDRIVE_ROOT": self.config["host"]["mdrive_root"],
            "LOCAL_PATH": self.config["host"]["local_path"],
            "SOC": self.config["logic"]["soc"],
            "BEFORE": self.config["logic"]["before"],
            "AFTER": self.config["logic"]["after"],
            "MODE": self.config["logic"]["mode"],
            "VERSION_JSON": self.config["logic"]["version_json"],
            "CONTAINER": self.config["docker"]["container"],
            "REMOTE_USER": self.config["remote"]["user"],
            "REMOTE_IP": self.config["remote"]["ip"],
            "REMOTE_DATA_ROOT": self.config["remote"]["data_root"],
        }
        full_env = os.environ.copy()
        full_env.update({k: str(v) for k, v in vars.items()})
        return full_env
