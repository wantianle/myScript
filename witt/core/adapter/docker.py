import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Union
from core.errors import CommandExecutionError, PathMappingError


class DockerAdapter:
    """负责在 Docker 容器内执行命令并处理路径映射"""

    def __init__(self, ctx) -> None:
        self.container = ctx.docker.container
        self.setup_env = ctx.docker.setup_env
        self.host_mount = Path(ctx.docker.host_mount).resolve()
        self.docker_mount = Path(ctx.docker.docker_mount)

    def _wrap_env(self, cmd: str) -> str:
        base_env = "export LANG=C.UTF-8 && export LC_ALL=C.UTF-8"
        return "{0} && source {1} && {2}".format(
            base_env,
            shlex.quote(self.setup_env),
            cmd,
        )

    def _build_exec_cmd(self, cmd: str, interactive: bool = False) -> list:
        docker_cmd = ["docker", "exec"]
        if interactive:
            docker_cmd.append("-it")
        docker_cmd.extend(
            [
                self.container,
                "/bin/bash",
                "-lc",
                self._wrap_env(cmd),
            ]
        )
        return docker_cmd

    def map_path(self, host_path: Union[str, Path]) -> str:
        try:
            h_path = Path(host_path).resolve()
            relative = h_path.relative_to(self.host_mount)
            d_path = self.docker_mount / relative
            return d_path.as_posix()
        except ValueError:
            raise PathMappingError(
                f"{host_path} 不在 {self.host_mount} 里，请重新确认路径..."
            )

    def execute(self, cmd: str) -> str:
        try:
            result = subprocess.run(
                self._build_exec_cmd(cmd),
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            detail = e.stderr.strip() or e.stdout.strip()
            if detail:
                raise CommandExecutionError("Docker 执行失败: {0}".format(detail)) from e
            raise CommandExecutionError("Docker 执行失败") from e

    def execute_interactive(self, cmd: str) -> None:
        completed_process = subprocess.run(
            self._build_exec_cmd(cmd, interactive=True),
            check=False,
        )
        if completed_process.returncode != 0:
            raise CommandExecutionError("Docker 执行失败")

    def remove(self, path: str) -> None:
        target_path = Path(path)
        if not target_path.exists():
            return
        try:
            target_path.unlink()
        except OSError as e:
            raise CommandExecutionError(
                "删除本地文件失败: {0}".format(target_path)
            ) from e

    def fetch_file(self, source_path: str, local_dest: Path) -> None:
        try:
            shutil.copy2(source_path, local_dest)
        except OSError as e:
            raise CommandExecutionError(
                "复制本地文件失败: {0}".format(source_path)
            ) from e
