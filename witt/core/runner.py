import subprocess
from pathlib import Path


class ScriptRunner:
    """任务执行器：负责本地调用外部脚本完成各项任务"""

    def __init__(self, ctx):
        self.ctx = ctx
        self.scripts_dir = Path(self.ctx.config["paths"]["scripts_dir"]).resolve()

    def _run_script(self, script_name: str, quit: bool, *args: str) -> None:
        """
        注入参数执行 Shell 脚本
        """
        script_path = self.scripts_dir / script_name
        if not script_path.exists():
            script_path = self.ctx.config["docker"]["dev_start"]
        env_vars = self.ctx.get_env_vars()
        bash_cmd = ["bash"]
        if self.ctx.config["env"]["debug"]:
            bash_cmd.append("-x")
        cmd = bash_cmd + [str(script_path)]
        try:
            subprocess.run(cmd, env=env_vars, text=True, check=True, capture_output=quit)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"{script_name} 脚本执行失败") from e

    def run_find_record(self) -> None:
        """
        注入参数执行 record 检索任务
        """
        self._run_script("find_record.sh", False)

    def run_restore_env(self) -> None:
        """
        注入参数执行环境同步还原
        """
        self._run_script("restore_env.sh", False)

    def run_dreamview(self) -> None:
        self._run_script("dreamview.sh", False)

    def run_docker(self) -> None:
        self._run_script("dev_start.sh", True, "--remove")
