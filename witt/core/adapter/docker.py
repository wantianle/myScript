import subprocess
import os
from pathlib import Path
from typing import Union
from interface import ui
from .base import BaseAdapter


class DockerAdapter(BaseAdapter):
    """负责在 Docker 容器内执行命令并处理路径映射"""

    def __init__(self, ctx) -> None:
        self.ctx = ctx
        self.container = ctx.config["docker"]["container"]
        self.setup_env = ctx.config["docker"]["setup_env"]
        self.host_mount = Path(ctx.config["docker"]["host_mount"]).resolve()
        self.docker_mount = Path(ctx.config["docker"]["docker_mount"])

    def wrap_env(self, cmd: str) -> str:
        """统一包装环境变量"""
        base_env = "export LANG=C.UTF-8 && export LC_ALL=C.UTF-8"
        return f"{base_env} && source {self.setup_env} && {cmd}"

    def remove(self, path: str) -> None:
        if os.path.exists(path):
            os.remove(path)

    def map_path(self, host_path: Union[str, Path]) -> str:
        """
        核心逻辑：将宿主机路径安全映射为容器内路径
        """
        try:
            h_path = Path(host_path).resolve()
            relative = h_path.relative_to(self.host_mount)
            d_path = self.docker_mount / relative
            return d_path.as_posix()
        except ValueError:
            ui.print_status(
                f"{host_path} 不在 {self.host_mount} 里，请重新确认路径...", "ERROR"
            )
            raise

    def execute(self, cmd: str) -> str:
        """
        在 Docker 容器中执行 Shell 命令并加载环境
        """
        # self.check_docker()
        full_cmd = f"docker exec {self.container} /bin/bash -c '{self.wrap_env(cmd)}'"
        result = subprocess.run(
            full_cmd, shell=True, capture_output=True, text=True, check=True
        )
        return result.stdout

    def execute_interactive(self, cmd: str) -> None:
        """
        用于 cyber_recorder play 等需要交互和实时刷新的命令
        """
        play_cmd = (
            f"docker exec -it {self.container} /bin/bash -c '{self.wrap_env(cmd)}'"
        )
        subprocess.run(play_cmd, shell=True, check=True)

    # def check_docker(self) -> None:
    #     """确保环境可用，否则尝试修复"""
    #     fmt = "{{.State.Running}}"
    #     res = subprocess.run(
    #         f"docker inspect -f {fmt} {self.container}",
    #         capture_output=True,
    #         text=True,
    #         shell=True,
    #     )
    #     exists, running = res.returncode == 0, res.stdout.strip()
    #     if exists:
    #         if running == "true":
    #             return
    #         else:
    #             res = subprocess.run(f"docker start {self.container}", shell=True)
    #             if res.returncode == 0:
    #                 return
    #     ui.print_status("容器启动失败，尝试重新创建并启动...", "WARN")
    #     self.runner.run_docker()
