import errno
import os
import subprocess
import sys
import pty
from pathlib import Path


class ScriptRunner:
    """负责本地调用外部脚本完成各项任务"""

    def __init__(self, ctx):
        self.ctx = ctx
        PROJECT_ROOT = Path(__file__).resolve().parents[1]
        self.scripts_dir = (PROJECT_ROOT / self.ctx.paths.scripts_dir).resolve()

    def _resolve_script_path(self, script_name: str) -> Path:
        """解析脚本路径，优先使用仓库内脚本。"""
        script_path = self.scripts_dir / script_name
        if not script_path.exists():
            script_path = Path(self.ctx.docker.docker_scripts) / script_name
        return script_path

    def _run_script(self, script_name: str, quiet: bool = False, *args: str) -> None:
        """注入环境变量并执行指定脚本。"""
        script_path = self._resolve_script_path(script_name)
        env_vars = self.ctx.get_env_vars()
        bash_cmd = ["bash"]
        # if self.ctx.config["env"]["debug"]:
        #     bash_cmd.append("-x")
        cmd = bash_cmd + [str(script_path), *args]
        try:
            subprocess.run(cmd, env=env_vars, text=True, check=True, capture_output=quiet)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"{script_name} 脚本执行失败") from e

    def _run_script_with_terminal_capture(self, script_name: str, *args: str) -> str:
        """在保留终端输出效果的同时捕获脚本输出。"""
        script_path = self._resolve_script_path(script_name)
        env_vars = self.ctx.get_env_vars()
        cmd = ["bash", str(script_path), *args]
        master_fd, slave_fd = pty.openpty()
        output_chunks = []
        process = None
        try:
            process = subprocess.Popen(
                cmd,
                env=env_vars,
                stdout=slave_fd,
                stderr=slave_fd,
            )
            os.close(slave_fd)
            slave_fd = -1
            while True:
                try:
                    chunk = os.read(master_fd, 4096)
                except OSError as exc:
                    if exc.errno == errno.EIO:
                        break
                    raise
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="replace")
                output_chunks.append(text)
                sys.stdout.write(text)
                sys.stdout.flush()
            return_code = process.wait()
            if return_code != 0:
                raise RuntimeError(f"{script_name} 脚本执行失败")
            return "".join(output_chunks)
        finally:
            if slave_fd >= 0:
                os.close(slave_fd)
            os.close(master_fd)
            if process is not None and process.poll() is None:
                process.wait()

    def run_find_record(self) -> None:
        """执行 record 查询脚本。"""
        self.ctx.find_record_output = self._run_script_with_terminal_capture(
            "find_record.sh"
        )

    def restore_runtime_environment(self) -> None:
        """恢复运行环境版本配置。"""
        self._run_script("restore_runtime_env.sh")

    def start_replay_stack(self) -> None:
        """启动标准回放相关模块。"""
        self._run_script("start_replay_stack.sh")

    def start_traffic_light_stack(self) -> None:
        """启动红绿灯回灌相关模块。"""
        self._run_script("start_traffic_light_stack.sh")

    def start_standard_replay_stack(self) -> None:
        """启动标准回放完整栈。"""
        self.start_replay_stack()

    def start_traffic_light_replay_stack(self) -> None:
        """启动红绿灯回灌所需的完整回放栈。"""
        self.start_standard_replay_stack()
        self.start_traffic_light_stack()

    def run_restore_env(self) -> None:
        """兼容旧接口：恢复运行环境。"""
        self.restore_runtime_environment()

    def run_tools(self) -> None:
        """兼容旧接口：启动标准回放栈。"""
        self.start_replay_stack()

    def run_traffic_light(self) -> None:
        """兼容旧接口：启动红绿灯栈。"""
        self.start_traffic_light_stack()

    def run_standard_replay_stack(self) -> None:
        """兼容旧接口：启动标准回放完整栈。"""
        self.start_standard_replay_stack()

    def run_traffic_light_replay_stack(self) -> None:
        """兼容旧接口：启动红绿灯完整回放栈。"""
        self.start_traffic_light_replay_stack()

    def run_docker(self) -> None:
        """启动底层 docker 开发容器。"""
        self._run_script("dev_start.sh", True, "--remove")

    def into_docker(self) -> None:
        """进入运行中的 docker 容器。"""
        self._run_script("dev_into.sh")
