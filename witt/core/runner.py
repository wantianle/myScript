import subprocess
from pathlib import Path


class ScriptRunner:
    """负责本地调用外部脚本完成各项任务"""

    def __init__(self, ctx):
        self.ctx = ctx
        PROJECT_ROOT = Path(__file__).resolve().parents[1]
        self.scripts_dir = (PROJECT_ROOT / self.ctx.paths.scripts_dir).resolve()

    def _run_script(self, script_name: str, quiet: bool = False, *args: str):
        """
        注入参数执行 Shell 脚本
        """
        script_path = self.scripts_dir / script_name
        if not script_path.exists():
            script_path = Path(self.ctx.docker.docker_scripts) / script_name
        env_vars = self.ctx.get_env_vars()
        bash_cmd = ["bash"]
        # if self.ctx.config["env"]["debug"]:
        #     bash_cmd.append("-x")
        cmd = bash_cmd + [str(script_path), *args]
        try:
            subprocess.run(cmd, env=env_vars, text=True, check=True, capture_output=quiet)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"{script_name} 脚本执行失败") from e

    def run_find_record(self):
        self._run_script("find_record.sh")

    def restore_runtime_environment(self):
        self._run_script("restore_runtime_env.sh")

    def start_replay_stack(self):
        self._run_script("start_replay_stack.sh")

    def start_traffic_light_stack(self):
        self._run_script("start_traffic_light_stack.sh")

    def start_standard_replay_stack(self):
        self.start_replay_stack()

    def start_traffic_light_replay_stack(self):
        self.start_standard_replay_stack()
        self.start_traffic_light_stack()

    def run_restore_env(self):
        self.restore_runtime_environment()

    def run_tools(self):
        self.start_replay_stack()

    def run_traffic_light(self):
        self.start_traffic_light_stack()

    def run_standard_replay_stack(self):
        self.start_standard_replay_stack()

    def run_traffic_light_replay_stack(self):
        self.start_traffic_light_replay_stack()

    def run_docker(self):
        self._run_script("dev_start.sh", True, "--remove")

    def into_docker(self):
        self._run_script("dev_into.sh")
