import errno
import os
import re
import subprocess
import sys
import pty
from pathlib import Path
from typing import List, TYPE_CHECKING

from core.engine import record_query
from core.engine import replay_stack
from core.engine import runtime_env
from core.errors import (
    CommandExecutionError,
    FindRecordError,
    ReplayStackError,
    RuntimeEnvironmentError,
    ScriptExecutionError,
)
from core.models import TaskEntry

if TYPE_CHECKING:
    from core.context import TaskContext


_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")


class RuntimeCoordinator:
    """负责协调查询、环境恢复、回放栈启动和开发环境入口。"""

    def __init__(self, ctx: "TaskContext") -> None:
        self.ctx = ctx
        self.record_query_service = record_query.RecordQueryService(ctx)
        self.replay_stack_manager = replay_stack.ReplayStackManager()
        PROJECT_ROOT = Path(__file__).resolve().parents[1]
        self.scripts_dir = (PROJECT_ROOT / self.ctx.paths.scripts_dir).resolve()

    def _resolve_script_path(self, script_name: str) -> Path:
        """解析脚本路径，优先使用仓库内脚本。"""
        script_path = self.scripts_dir / script_name
        if not script_path.exists():
            script_path = Path(self.ctx.docker.docker_scripts) / script_name
        return script_path

    def _build_script_execution_error(
        self,
        script_name: str,
        output_text: str,
    ) -> ScriptExecutionError:
        """将脚本输出解析为结构化异常，优先提取脚本中的 ERROR 行。"""
        normalized_lines = [
            _ANSI_ESCAPE_RE.sub("", line).strip()
            for line in output_text.splitlines()
            if _ANSI_ESCAPE_RE.sub("", line).strip()
        ]
        error_lines = []
        for line in normalized_lines:
            if "[ERROR]" not in line:
                continue
            error_message = line.split("[ERROR]", 1)[1].strip()
            if error_message:
                error_lines.append(error_message)
        if not error_lines:
            return ScriptExecutionError(
                script_name,
                "{0} 脚本执行失败".format(script_name),
            )
        user_facing_errors = [
            line
            for line in error_lines
            if "退出状态码:" not in line and "命令在第 " not in line
        ]
        summary = user_facing_errors[0] if user_facing_errors else error_lines[0]
        details = [line for line in error_lines if line != summary]
        return ScriptExecutionError(
            script_name,
            summary,
            details=details,
        )

    def _run_script(self, script_name: str, quiet: bool = False, *args: str) -> None:
        """注入环境变量并执行辅助脚本。"""
        script_path = self._resolve_script_path(script_name)
        env_vars = self.ctx.get_env_vars()
        bash_cmd = ["bash"]
        # if self.ctx.config["env"]["debug"]:
        #     bash_cmd.append("-x")
        cmd = bash_cmd + [str(script_path), *args]
        completed_process = subprocess.run(
            cmd,
            env=env_vars,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        script_output = completed_process.stdout or ""
        if not quiet and script_output:
            sys.stdout.write(script_output)
            sys.stdout.flush()
        if completed_process.returncode != 0:
            raise self._build_script_execution_error(script_name, script_output)

    def _run_script_with_terminal_capture(
        self, script_name: str, echo_output: bool = True, *args: str
    ) -> str:
        """按需回显终端输出，并同时捕获辅助脚本输出。"""
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
                if echo_output:
                    sys.stdout.write(text)
                    sys.stdout.flush()
            return_code = process.wait()
            if return_code != 0:
                raise self._build_script_execution_error(
                    script_name,
                    "".join(output_chunks),
                )
            return "".join(output_chunks)
        finally:
            if slave_fd >= 0:
                os.close(slave_fd)
            os.close(master_fd)
            if process is not None and process.poll() is None:
                process.wait()

    def run_find_record(self) -> List[TaskEntry]:
        """执行 record 查询并返回任务列表。"""
        try:
            return self.record_query_service.run_query()
        except CommandExecutionError as e:
            raise ScriptExecutionError(
                "record_query",
                "无法连接车机或找不到对应record 文件！",
                details=[str(e)],
            ) from e
        except FindRecordError as e:
            raise ScriptExecutionError("record_query", str(e)) from e

    def restore_runtime_environment(self) -> None:
        """恢复运行环境版本配置并执行 vmc.sh 安装依赖。"""
        vmc_path = Path(self.ctx.host.mdrive_root) / "vmc.sh"
        try:
            runtime_changed = runtime_env.restore_runtime_environment(
                version_path=Path(str(self.ctx.logic.version)),
                vmc_path=vmc_path,
                vehicle_name=self.ctx.vehicle,
            )
            if not runtime_changed:
                return
            # 执行 vmc.sh 脚本来安装依赖
            env_vars = self.ctx.get_env_vars()
            cmd = ["bash", str(vmc_path)]
            completed_process = subprocess.run(
                cmd,
                env=env_vars,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            script_output = completed_process.stdout or ""
            if script_output:
                sys.stdout.write(script_output)
                sys.stdout.flush()
            if completed_process.returncode != 0:
                raise self._build_script_execution_error("vmc.sh", script_output)
        except RuntimeEnvironmentError as e:
            raise ScriptExecutionError("runtime_environment", str(e)) from e

    def start_replay_stack(self) -> None:
        """启动标准回放相关模块。"""
        try:
            self.replay_stack_manager.start_standard_replay_stack(self.ctx)
        except ReplayStackError as e:
            raise ScriptExecutionError("standard_replay_stack", str(e)) from e

    def start_traffic_light_stack(self) -> None:
        """启动红绿灯回灌相关模块。"""
        try:
            self.replay_stack_manager.start_traffic_light_stack(self.ctx)
        except ReplayStackError as e:
            raise ScriptExecutionError("traffic_light_replay_stack", str(e)) from e

    def start_standard_replay_stack(self) -> None:
        """启动标准回放完整栈。"""
        self.start_replay_stack()

    def start_traffic_light_replay_stack(self) -> None:
        """启动红绿灯回灌所需的完整回放栈。"""
        self.start_standard_replay_stack()
        self.start_traffic_light_stack()

    def run_docker(self) -> None:
        """启动底层 docker 开发容器。"""
        self._run_script("dev_start.sh", True, "--remove")

    def into_docker(self) -> None:
        """进入运行中的 docker 容器。"""
        self._run_script("dev_into.sh")
