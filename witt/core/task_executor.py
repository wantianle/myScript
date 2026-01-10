import subprocess
from pathlib import Path


class TaskExecutor:
    """任务执行器：负责本地调用外部脚本完成各项任务"""
    def __init__(self, ctx):
        self.ctx = ctx
        project_root = Path(__file__).resolve().parents[1]
        self.scripts_dir = project_root / self.ctx.config["paths"]["scripts_dir"]

    def _run_script(self, script_name: str) -> None:
        """
        注入参数执行 Shell 脚本
        """
        script_path = self.scripts_dir / script_name
        env_vars = self.ctx.get_env_vars()
        bash_base = ["bash"]
        if self.ctx.config.get("env").get("debug"):
            bash_base.append("-x")
        cmd = bash_base + [str(script_path)]
        try:
            subprocess.run(cmd, env=env_vars, check=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"{script_name} 脚本执行失败") from e

    def run_find_record(self) -> None:
        """
        注入参数执行 record 检索任务
        """
        self._run_script("find_record.sh")

    def run_restore_env(self) -> None:
        """
        注入参数执行环境同步还原
        """
        self._run_script("restore_env.sh")

    def run_dreamview(self) -> None:
        self._run_script("dreamview.sh")
