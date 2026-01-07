import os
import logging
import tempfile
import shutil
import atexit
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict


@dataclass
class TaskContext:
    config: dict
    vehicle: str
    target_date: str
    work_dir: Path = field(init=False)
    temp_dir: Path = field(init=False)
    manifest_path: Path = field(init=False)

    def __post_init__(self):
        """构建标准工作目录结构"""
        base_output = Path(self.config["host"]["dest_root"])
        self.work_dir = base_output / self.vehicle / self.target_date
        self.log_dir = self.work_dir / "log"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir = Path(tempfile.mkdtemp(prefix="witt_session_"))
        self.manifest_path = self.temp_dir / "tasks.list"
        atexit.register(self._cleanup_temp)
        logging.debug(f"Temporary manifest created at: {self.manifest_path}")

    def _cleanup_temp(self):
        """退出时的清理动作"""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
            # print(f"\n[System] Volatile session data at {self.temp_dir} cleaned.")

    def setup_logger(self):
        """配置日志系统：支持控制台与文件双向输出"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = self.log_dir / f"SNAP_{timestamp}.log"

        logger = logging.getLogger()
        logger.setLevel(logging.INFO)

        # 在重新配置前清理旧的 Handler，防止日志重复打印
        if logger.hasHandlers():
            logger.handlers.clear()

        # 定义统一的日志格式
        log_format = "%(asctime)s [%(levelname)s] %(message)s"
        formatter = logging.Formatter(log_format)

        # 控制台 Handler
        sh = logging.StreamHandler()
        sh.setFormatter(formatter)
        logger.addHandler(sh)

        # 文件 Handler (UTF-8 编码确保中文路径不乱码)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    def get_env_vars(self) -> Dict[str, str]:
        """构建注入 Shell 脚本的环境变量字典"""
        cfg = self.config

        # 透传给 Shell 脚本的业务变量映射
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

        # 所有环境变量的值必须显式转为 string，否则 subprocess 会报错
        full_env = os.environ.copy()
        processed_vars = {k: str(v) for k, v in vars.items()}
        full_env.update(processed_vars)
        return full_env
