import logging
import subprocess
import sys
from pathlib import Path
from typing import Union


class DockerAdapter:
    """负责在 Docker 容器内执行命令并处理路径映射"""

    def __init__(self, ctx):
        # self.image = ctx.config["docker"]["image"]
        self.container = ctx.config["docker"]["container"]
        self.dev_into = ctx.config["docker"]["dev_into"]
        self.dev_start = ctx.config["docker"]["dev_start"]
        self.setup_env = ctx.config["docker"]["setup_env"]
        self.host_mount = Path(ctx.config["docker"]["host_mount"]).resolve()
        self.docker_path = Path(ctx.config["docker"]["docker_mount"])

    def _get_status(self, container: str):
        """通用检查函数：获取容器或镜像的状态"""
        fmt = "{{.State.Running}}"
        res = subprocess.run(
            f"docker inspect -f {fmt} {container}",
            capture_output=True,
            text=True,
            shell=True,
        )
        return res.returncode == 0, res.stdout.strip()

    def check_docker(self):
        """确保环境可用，否则尝试修复"""
        exists, running = self._get_status(self.container)
        if exists:
            if running == "true":
                return
            else:
                res = subprocess.run(f"docker start {self.container}", shell=True)
                if res.returncode == 0:
                    return
        logging.warning(f"容器启动失败，尝试重新创建并启动...")
        subprocess.run(
            f"bash {self.dev_start} --remove",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            shell=True
        )

    def map_path(self, host_path: Union[str, Path]) -> str:
        """
        核心逻辑：将宿主机路径安全映射为容器内路径
        """
        try:
            h_path = Path(host_path).resolve()
            relative = h_path.relative_to(self.host_mount)
            d_path = self.docker_path / relative
            return d_path.as_posix()
        except ValueError:
            logging.error(
                f"{host_path} 不在 {self.host_mount} 里，请重新确认路径..."
            )
            sys.exit(1)

    def execute(self, cmd: str) -> str:
        """
        在 Docker 容器中执行 Shell 命令并加载环境
        """
        self.check_docker()
        env_cmds = "export LANG=C.UTF-8 && export LC_ALL=C.UTF-8"
        source_cmd = f"source {self.setup_env}"
        full_cmd = f"docker exec {self.container} /bin/bash -c '{env_cmds} && {source_cmd} && {cmd}'"
        try:
            result = subprocess.run(
                full_cmd, shell=True, capture_output=True, text=True, check=True
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            error_detail = e.stderr.strip() or e.stdout.strip()
            logging.error(
                f"\n[Docker Exec Error]\nCommand: {cmd}\nDetail: {error_detail}"
            )
            raise RuntimeError(error_detail)

    def execute_interactive(self, cmd: str, scripts):
        """
        用于 cyber_recorder play 等需要交互和实时刷新的命令
        """
        scripts.run_restore_env()
        env_setup = "export LANG=C.UTF-8 && export LC_ALL=C.UTF-8"
        play_cmd = f"docker exec -it {self.container} /bin/bash -c '{env_setup} && source {self.setup_env} && {cmd}'"
        subprocess.run(play_cmd, shell=True, check=True)
