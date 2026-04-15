import os
import subprocess
import logging
from typing import Union, List
from pathlib import Path
from .base import BaseAdapter
from core.errors import CommandExecutionError

logger = logging.getLogger(__name__)


class SSHAdapter(BaseAdapter):
    """远程执行命令适配器（精简重构版）"""

    def __init__(self, config) -> None:
        self.user = config["remote"]["user"]
        self.ip = config["remote"]["ip"]
        self.setup_env = config["docker"]["setup_env"]
        self.remote_addr = f"{self.user}@{self.ip}"
        self.env_setup_cmd = (
            "export LANG=C.UTF-8 && export LC_ALL=C.UTF-8 && "
            "export GLOG_log_dir=/tmp && export MDRIVE_ROOT_DIR='/mdrive' && "
            "export MDRIVE_DEP_DIR='/mdrive/mdrive_dep'"
        )

    def _get_common_opts(self) -> List[str]:
        """统一 SSH/SCP 的安全与连接参数"""
        return [
            "-o",
            "ConnectTimeout=5",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "LogLevel=ERROR",
        ]

    def _call(self, cmd: List[str], error_msg: str) -> str:
        """统一的底层系统调用处理"""
        env_c = os.environ.copy()
        env_c["LC_ALL"] = "C"
        try:
            result = subprocess.run(
                cmd, env=env_c, capture_output=True, text=True, check=True
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            detail = e.stderr.strip() or e.stdout.strip()
            logger.error(f"CMD FAILED: {' '.join(cmd)} | DETAIL: {detail}")
            raise CommandExecutionError(f"{error_msg}: {detail}") from e

    def remove(self, path: str) -> None:
        self.execute(f"rm -f {path}")

    def map_path(self, host_path: Union[str, Path]) -> str:
        return str(host_path)

    def fetch_file(self, remote_path: str, local_dest: Path) -> None:
        """从远程拉取文件"""
        cmd = (
            ["scp"]
            + self._get_common_opts()
            + [f"{self.remote_addr}:{remote_path}", str(local_dest)]
        )
        self._call(cmd, "SCP 同步失败")

    def execute(self, cmd: str) -> str:
        """在远程执行 Shell 命令"""
        full_remote_cmd = f"{self.env_setup_cmd} && source {self.setup_env} && {cmd}"
        ssh_cmd = (
            ["ssh"]
            + self._get_common_opts()
            + [
                "-o",
                "ControlMaster=auto",
                "-o",
                "ControlPath=/tmp/ssh_mux_%r@%h:%p",
                "-o",
                "ControlPersist=5m",
                self.remote_addr,
                f"LC_ALL=C {full_remote_cmd}",
            ]
        )
        return self._call(ssh_cmd, "SSH 执行失败")
