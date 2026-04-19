import errno
import os
import re
import shlex
import subprocess
import sys
import pty
from pathlib import Path
from typing import List

from core.engine import record_finder
from core.errors import CommandExecutionError, FindRecordError, ScriptExecutionError
from core.models import TaskEntry


_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")


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
        """注入环境变量并执行指定脚本。"""
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
        self,
        script_name: str,
        echo_output: bool = True,
        *args: str
    ) -> str:
        """按需回显终端输出，并同时捕获脚本输出。"""
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

    def _resolve_find_record_root(self) -> Path:
        """按当前模式解析查询根目录。"""
        if self.ctx.logic.mode == 2:
            return (
                Path(self.ctx.host.nas_root)
                / self.ctx.target_date[:8]
                / self.ctx.vehicle
            )
        return Path(str(self.ctx.host.data_root).rstrip("/"))

    def _run_remote_command(self, cmd_text: str) -> str:
        """执行远程查询命令，不依赖 mdrive 运行时环境。"""
        remote_addr = "{0}@{1}".format(
            self.ctx.remote.user,
            self.ctx.remote.ip,
        )
        ssh_cmd = [
            "ssh",
            "-o",
            "ConnectTimeout=3",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "LogLevel=ERROR",
            "-o",
            "ControlMaster=auto",
            "-o",
            "ControlPath=/tmp/ssh_mux_%r@%h:%p",
            "-o",
            "ControlPersist=5m",
            remote_addr,
            "LC_ALL=C {0}".format(cmd_text),
        ]
        try:
            completed_process = subprocess.run(
                ssh_cmd,
                env=os.environ.copy(),
                capture_output=True,
                text=True,
                check=True,
            )
            return completed_process.stdout
        except subprocess.CalledProcessError as e:
            detail = e.stderr.strip() or e.stdout.strip()
            raise CommandExecutionError(
                "SSH 执行失败: {0}".format(detail)
            ) from e

    def _run_remote_find_paths(self) -> List[str]:
        """读取远程查询根目录下的候选 record/tag 路径。"""
        remote_root = str(self.ctx.remote.data_root).rstrip("/")
        target_date = self.ctx.target_date
        soc_filter = str(getattr(self.ctx.logic, "soc", ""))
        record_filter = "-name '{0}*record*'".format(target_date)
        if soc_filter:
            record_filter = "-ipath '*{0}*' {1}".format(
                soc_filter,
                record_filter,
            )
        find_cmd = (
            "find {0} -type f \\( \\( {1} \\) -o -name '*tag*' -name '*{2}*' \\) 2>/dev/null"
        ).format(
            shlex.quote(remote_root),
            record_filter,
            target_date,
        )
        raw_output = self._run_remote_command(find_cmd)
        return [
            line.strip()
            for line in raw_output.splitlines()
            if line.strip()
        ]

    def _read_remote_text(self, path_text: str) -> str:
        """读取远程文本文件内容。"""
        try:
            return self._run_remote_command(
                "cat {0}".format(shlex.quote(path_text))
            )
        except CommandExecutionError as e:
            raise ScriptExecutionError(
                "find_record",
                "读取远程 tag 文件失败: {0}".format(path_text),
                details=[str(e)],
            ) from e

    def run_find_record(self) -> List[TaskEntry]:
        """执行 record 查询脚本。"""
        if self.ctx.logic.mode == 3:
            try:
                path_texts = self._run_remote_find_paths()
            except CommandExecutionError as e:
                raise ScriptExecutionError(
                    "find_record",
                    "无法连接车机或找不到对应record 文件！",
                    details=[str(e)],
                ) from e
            try:
                task_entries = record_finder.find_tasks_from_path_texts(
                    path_texts,
                    self._read_remote_text,
                    target_date=self.ctx.target_date,
                    before=int(self.ctx.logic.before),
                    after=int(self.ctx.logic.after),
                    soc_filter=str(getattr(self.ctx.logic, "soc", "")),
                    source_root=str(self.ctx.remote.data_root),
                )
            except FindRecordError as e:
                raise ScriptExecutionError("find_record", str(e)) from e
            self.ctx.find_record_output = record_finder.dump_manifest(
                task_entries,
                self.ctx.manifest_path,
            )
            return task_entries
        try:
            task_entries = record_finder.find_local_tasks(
                self._resolve_find_record_root(),
                target_date=self.ctx.target_date,
                before=int(self.ctx.logic.before),
                after=int(self.ctx.logic.after),
                soc_filter=str(getattr(self.ctx.logic, "soc", "")),
            )
        except FindRecordError as e:
            raise ScriptExecutionError("find_record", str(e)) from e
        self.ctx.find_record_output = record_finder.dump_manifest(
            task_entries,
            self.ctx.manifest_path,
        )
        return task_entries

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

    def run_docker(self) -> None:
        """启动底层 docker 开发容器。"""
        self._run_script("dev_start.sh", True, "--remove")

    def into_docker(self) -> None:
        """进入运行中的 docker 容器。"""
        self._run_script("dev_into.sh")
