import os
import logging
import tempfile
import shutil
import atexit
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict


class _WittFormatter(logging.Formatter):
    """私有格式化器：全自动处理颜色与格式"""

    COLORS = {
        "DEBUG": "\033[0;90m",
        "INFO": "\033[0;32m",
        "WARNING": "\033[0;33m",
        "ERROR": "\033[0;31m",
        "RESET": "\033[0m",
    }

    def format(self, record):
        # 自动根据级别染色的模板
        color = self.COLORS.get(record.levelname, self.COLORS["RESET"])
        fmt = f"{color}%(asctime)s [%(levelname)s] %(message)s{self.COLORS['RESET']}"
        # 动态创建格式化器（datefmt 设为简短格式）
        return logging.Formatter(fmt, datefmt="%H:%M:%S").format(record)


@dataclass
class TaskContext:
    config: dict
    vehicle: str
    target_date: str
    work_dir: Path = field(init=False)
    log_dir: Path = field(init=False)
    temp_dir: Path = field(init=False)
    manifest_path: Path = field(init=False)
    _logger_ready: bool = field(default=False, init=False)

    def __post_init__(self):
        """构建目录结构，但不初始化日志文件"""
        base_output = Path(self.config["host"]["dest_root"])
        self.work_dir = base_output / self.vehicle / self.target_date
        self.log_dir = self.work_dir / "log"

        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.temp_dir = Path(tempfile.mkdtemp(prefix="witt_session_"))
        self.manifest_path = self.temp_dir / "tasks.list"
        atexit.register(self._cleanup_temp)

    def _cleanup_temp(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def setup_logger(self):
        """
        只有在真正写日志时才创建文件。
        """
        if self._logger_ready:
            return
        # level_name = self.config.get("env", {}).get("log_level", "INFO").upper()
        # level = getattr(logging, level_name, logging.INFO)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = self.log_dir / f"witt_{timestamp}.log"

        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)

        if logger.hasHandlers():
            logger.handlers.clear()

        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

        sh = logging.StreamHandler()
        sh.setFormatter(_WittFormatter())
        sh.setLevel(logging.INFO)
        logger.addHandler(sh)

        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(formatter)
        fh.setLevel(logging.DEBUG)
        logger.addHandler(fh)

        self._logger_ready = True
        # logging.info(f"--- Log Session Active: {log_file.name} ---")

    def get_library_fingerprint(self) -> str:
        """
        [性能优化] 只检查当前 Vehicle/Date 目录的状态
        原理：如果在这个目录下下载了新文件，work_dir 或 log_dir 的 mtime 必变
        """
        if not self.work_dir.exists():
            return "none"
        mtime_sum = self.work_dir.stat().st_mtime + self.log_dir.stat().st_mtime
        return f"{self.vehicle}_{self.target_date}_{mtime_sum}"

    def get_env_vars(self) -> Dict[str, str]:
        """构建注入 Shell 脚本的环境变量字典"""
        cfg = self.config
        vars = {
            "NAS_ROOT": cfg["host"]["nas_root"],
            "DEST_ROOT": cfg["host"]["dest_root"],
            "LOCAL_PATH": cfg["host"]["local_path"],
            "VMC_SH": cfg["host"]["vmc_sh_path"],
            "MDRIVE_ROOT": cfg["host"]["mdrive_root"],
            "CONTAINER": cfg["docker"]["container_name"],
            "LOOKBACK": cfg["logic"]["lookback"],
            "LOOKFRONT": cfg["logic"]["lookfront"],
            "MODE": cfg["env"]["mode"],
            "REMOTE_USER": cfg["remote"]["user"],
            "REMOTE_IP": cfg["remote"]["ip"],
            "REMOTE_DATA_ROOT": cfg["remote"]["data_root"],
        }
        full_env = os.environ.copy()
        full_env.update({k: str(v) for k, v in vars.items()})
        return full_env
