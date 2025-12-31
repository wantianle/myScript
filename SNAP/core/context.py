import os
import logging
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
    version_json_path: str = ""

    def __post_init__(self):
        """构建标准工作目录结构"""
        base_output = Path(self.config["host"]["dest_root"])
        self.work_dir = base_output / self.vehicle / self.target_date
        self.log_dir = self.work_dir / "log"
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def setup_logger(self):
        """配置日志系统：支持控制台与文件双向输出"""
        # 格式化时间戳，避免文件名出现空格或非法字符
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
        c = self.config

        # 透传给 Shell 脚本的业务变量映射
        vars = {
            "NAS_ROOT": c["host"]["nas_root"],
            "DEST_ROOT": c["host"]["dest_root"],
            "LOCAL_PATH": c["host"]["local_path"],
            "VMC_SH": c["host"]["vmc_sh_path"],
            "MDRIVE_ROOT": c["host"]["mdrive_root"],
            "CONTAINER": c["docker"]["container_name"],
            # "VEHICLE": self.vehicle,
            # "DATATIME": self.target_date,
            # "SOC": c["env"]["soc"],
            "LOOKBACK": c["logic"]["lookback"],
            "LOOKFRONT": c["logic"]["lookfront"],
            "MODE": c["env"]["mode"],
            "REMOTE_USER": c["remote"]["user"],
            "REMOTE_IP": c["remote"]["ip"],
            "REMOTE_DATA_ROOT": c["remote"]["data_root"],
        }

        # 所有环境变量的值必须显式转为 string，否则 subprocess 会报错
        full_env = os.environ.copy()
        processed_vars = {k: str(v) for k, v in vars.items()}
        full_env.update(processed_vars)
        return full_env
