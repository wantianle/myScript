import subprocess
import logging
from pathlib import Path
from typing import Union


class DockerExecutor:
    def __init__(self, config: dict):
        self.container = config["docker"]["container_name"]
        self.setup_bash = config["docker"]["setup_bash"]
        self.host_mount = Path(config["docker"]["host_mount"]).resolve()
        self.docker_mount = Path(config["docker"]["docker_mount"])

    def to_docker_path(self, host_path: Union[str, Path]) -> str:
        """
        核心逻辑：将宿主机路径安全映射为容器内路径
        """
        try:
            h_path = Path(host_path).resolve()
            relative = h_path.relative_to(self.host_mount)
            d_path = self.docker_mount / relative
            return d_path.as_posix()
        except ValueError:
            # 如果 host_path 不在挂载目录下，原样返回或记录警告
            logging.debug(
                f"Path {host_path} is not within host_mount, returning original."
            )
            return str(host_path)

    def execute(self, cmd: str) -> str:
        """
        在 Docker 容器中执行 Shell 命令
        注入 UTF-8 并加载环境
        """
        # 强制开启 UTF-8 支持以处理中文路径，并加载环境
        env_cmds = "export LANG=C.UTF-8 && export LC_ALL=C.UTF-8"
        source_cmd = f"source {self.setup_bash}"

        full_cmd = (
            f"docker exec {self.container} /bin/bash -c "
            f"'{env_cmds} && {source_cmd} && {cmd}'"
        )

        try:
            # text=True 自动处理编码，capture_output 捕获返回
            result = subprocess.run(
                full_cmd, shell=True, capture_output=True, text=True, check=True
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            error_detail = e.stderr.strip() or e.stdout.strip()
            logging.error(
                f"\n[Docker Exec Error]\nCommand: {cmd}\nDetail: {error_detail}"
            )
            raise RuntimeError(f"Docker command failed: {error_detail}")
