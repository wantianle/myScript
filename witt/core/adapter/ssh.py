from pathlib import Path
import os
import shlex
import subprocess
from typing import List, Union

from core.errors import CommandExecutionError


class SSHAdapter:
    """远程执行命令适配器"""

    def __init__(self, ctx) -> None:
        self.user = ctx.remote.user
        self.ip = ctx.remote.ip
        self.setup_env = ctx.docker.setup_env
        self.remote_addr = f"{self.user}@{self.ip}"
        self.base_env_cmd = (
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

    def _wrap_env(self, cmd: str) -> str:
        return "{0} && source {1} && {2}".format(
            self.base_env_cmd,
            shlex.quote(self.setup_env),
            cmd,
        )

    def _build_ssh_cmd(self, cmd: str, interactive: bool = False) -> List[str]:
        ssh_cmd = ["ssh"]
        if interactive:
            ssh_cmd.append("-t")
        ssh_cmd.extend(
            self._get_common_opts()
            + [
                "-o",
                "ControlMaster=auto",
                "-o",
                "ControlPath=/tmp/ssh_mux_%r@%h:%p",
                "-o",
                "ControlPersist=5m",
                self.remote_addr,
                "LC_ALL=C {0}".format(self._wrap_env(cmd)),
            ]
        )
        return ssh_cmd

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
            if detail:
                raise CommandExecutionError("{0}: {1}".format(error_msg, detail)) from e
            raise CommandExecutionError(error_msg) from e

    def remove(self, path: str) -> None:
        self.execute("rm -f {0}".format(shlex.quote(path)))

    def map_path(self, host_path: Union[str, Path]) -> str:
        return str(host_path)

    def fetch_file(self, remote_path: str, local_dest: Path) -> None:
        """从远程拉取文件"""
        cmd = (
            ["scp"]
            + self._get_common_opts()
            + [
                "{0}:{1}".format(self.remote_addr, shlex.quote(remote_path)),
                str(local_dest),
            ]
        )
        self._call(cmd, "SCP 同步失败")

    def execute(self, cmd: str) -> str:
        """在远程执行 Shell 命令"""
        return self._call(self._build_ssh_cmd(cmd), "SSH 执行失败")

    def execute_interactive(self, cmd: str) -> None:
        env_c = os.environ.copy()
        env_c["LC_ALL"] = "C"
        completed_process = subprocess.run(
            self._build_ssh_cmd(cmd, interactive=True),
            env=env_c,
            check=False,
        )
        if completed_process.returncode != 0:
            raise CommandExecutionError("SSH 执行失败")
