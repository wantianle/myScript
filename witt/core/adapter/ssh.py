import os
import subprocess
from typing import Union
from pathlib import Path
from interface import ui
from .base import BaseAdapter


class SSHAdapter(BaseAdapter):
    """远程执行命令拼接"""

    def __init__(self, config) -> None:
        self.user = config["remote"]["user"]
        self.ip = config["remote"]["ip"]
        self.setup_env = config["docker"]["setup_env"]

    def map_path(self, host_path: Union[str, Path]) -> str:
        """远程模式下通常不需要路径映射，直接返回原路径"""
        return str(host_path)

    def fetch_file(self, remote_path: str, local_dest: Path) -> None:
        """使用 scp 从远程车机拉回文件"""
        env_c = os.environ.copy()
        env_c["LC_ALL"] = "C"
        remote_uri = f"{self.user}@{self.ip}:{remote_path}"
        subprocess.run(
            ["scp", "-q", remote_uri, str(local_dest)], env=env_c, check=True
        )

    def get_size(self, path: str) -> int:
        res = self.execute(f"stat -c %s {path}")
        return int(res.strip()) if res else 0

    def remove(self, path: str) -> None:
        self.execute(f"rm -f {path}")

    def execute(self, cmd: str) -> str:
        """通过 SSH 在远程车机执行命令"""
        env_setup = "export LANG=C.UTF-8 && export LC_ALL=C.UTF-8 && export GLOG_log_dir=/tmp && export MDRIVE_ROOT_DIR='/mdrive' && export MDRIVE_DEP_DIR='/mdrive/mdrive_dep'"
        remote_cmd = f"{env_setup} && source {self.setup_env} && {cmd}"

        # 构造 SSH 命令
        full_cmd = [
            "ssh",
            "-o",
            "ConnectTimeout=3",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",  # 不记录 known_hosts，防止 IP 变动报错
            "-o",
            "SendEnv=-LC_*",
            "-o",
            "LogLevel=ERROR",  # 只显示错误，不显示登录 Banner
            "-o",
            "ControlMaster=auto",  # 开启持久化复用
            "-o",
            "ControlPath=~/.ssh/mux-%r@%h:%p",  # Socket 文件路径
            "-o",
            "ControlPersist=5m",  # 5分钟内没指令才真正断开
            f"{self.user}@{self.ip}",
            f"LC_ALL=C {remote_cmd}",  # 强制远程环境为标准 C 语言环境
        ]

        try:
            result = subprocess.run(
                full_cmd, capture_output=True, text=True, check=True
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            ui.print_status("SSH Exec Error", "ERROR")
            raise e
