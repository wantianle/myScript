import subprocess
import os
from pathlib import Path
from typing import Union
from interface import ui


class DockerAdapter():
    """负责在 Docker 容器内执行命令并处理路径映射"""

    def __init__(self, ctx):
        self.ctx = ctx
        self.container = ctx.config["docker"]["container"]
        self.setup_env = ctx.config["docker"]["setup_env"]
        self.host_mount = Path(ctx.config["docker"]["host_mount"]).resolve()
        self.docker_mount = Path(ctx.config["docker"]["docker_mount"])

    def wrap_env(self, cmd: str) -> str:
        base_env = "export LANG=C.UTF-8 && export LC_ALL=C.UTF-8"
        return f"{base_env} && source {self.setup_env} && {cmd}"

    def remove(self, path: str):
        if os.path.exists(path):
            os.remove(path)

    def map_path(self, host_path: Union[str, Path]) -> str:
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
        full_cmd = f"docker exec {self.container} /bin/bash -c '{self.wrap_env(cmd)}'"
        result = subprocess.run(
            full_cmd, shell=True, capture_output=True, text=True, check=True
        )
        return result.stdout

    def execute_interactive(self, cmd: str):
        play_cmd = (
            f"docker exec -it {self.container} /bin/bash -c '{self.wrap_env(cmd)}'"
        )
        subprocess.run(play_cmd, shell=True, check=True)
