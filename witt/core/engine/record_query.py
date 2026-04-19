import os
import shlex
import subprocess
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

from core.engine.record_finder import RecordFinderManager
from core.errors import CommandExecutionError
from core.models import TaskEntry

if TYPE_CHECKING:
    from core.context import TaskContext


class RecordQueryService:
    """负责按模式执行 record 查询并返回任务列表。"""

    def __init__(
        self,
        ctx: "TaskContext",
        finder_manager: Optional[RecordFinderManager] = None,
    ) -> None:
        self.ctx = ctx
        self.finder_manager = finder_manager or RecordFinderManager()

    def run_query(self) -> List[TaskEntry]:
        """执行本地、NAS 或远程查询并返回任务列表。"""
        if self.ctx.logic.mode == 3:
            task_entries = self.finder_manager.find_tasks_from_path_texts(
                self._run_remote_find_paths(),
                self._read_remote_text,
                target_date=self.ctx.target_date,
                before=int(self.ctx.logic.before),
                after=int(self.ctx.logic.after),
                soc_filter=str(getattr(self.ctx.logic, "soc", "")),
                source_root=str(self.ctx.remote.data_root),
            )
        else:
            task_entries = self.finder_manager.find_local_tasks(
                self._resolve_find_record_root(),
                target_date=self.ctx.target_date,
                before=int(self.ctx.logic.before),
                after=int(self.ctx.logic.after),
                soc_filter=str(getattr(self.ctx.logic, "soc", "")),
            )
        return task_entries

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
        return self._run_remote_command(
            "cat {0}".format(shlex.quote(path_text))
        )
