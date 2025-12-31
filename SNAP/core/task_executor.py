import subprocess
import logging
from pathlib import Path
from typing import List, Optional, Union


class TaskExecutor:
    def __init__(self, ctx):
        self.ctx = ctx
        project_root = Path(__file__).resolve().parent.parent
        paths_cfg = self.ctx.config.get("paths", {})
        rel_scripts_path = paths_cfg.get("scripts_dir", "scripts")
        self.scripts_dir = (project_root / rel_scripts_path).resolve()

        logging.debug(f"TaskExecutor initialized with scripts_dir: {self.scripts_dir}")

    def _run_script(self, script_name: str, args: List[Union[str, int, float]]):
        """
        执行 Shell 脚本
        """
        script_path = self.scripts_dir / script_name
        if not script_path.exists():
            error_msg = f"未找到脚本文件: {script_path}"
            logging.error(error_msg)
            raise FileNotFoundError(error_msg)
        string_args = [str(a) for a in args]
        env_vars = self.ctx.get_env_vars()
        bash_base = ["bash"]
        if self.ctx.config.get("env", {}).get("debug"):
            bash_base.append("-x")

        cmd = bash_base + [str(script_path)] + string_args

        logging.info(f"Running script: {script_name} | Command: {' '.join(cmd)}")
        try:
            return subprocess.run(cmd, env=env_vars, check=True)
        except subprocess.CalledProcessError as e:
            logging.error(f"脚本 {script_name} 执行失败，退出码: {e.returncode}")
            raise

    def run_find_record(self, local_data: List[str]):
        """
        执行 record 检索任务
        参数由 main.py 编排传入，此处负责标准化注入基础参数
        """
        base_args = [
            "-t",
            self.ctx.target_date,
            "-v",
            self.ctx.vehicle,
        ]
        full_args = base_args + local_data
        return self._run_script("find_record.sh", full_args)

    def find_version_json(self, search_path: Union[str, Path]) -> Optional[str]:
        """
        在指定目录下递归寻找第一个出现的 version.json
        """
        search_root = Path(search_path)
        logging.debug(f"正在搜索版本信息: {search_root}")
        # rglob 返回一个生成器，next() 获取第一个匹配项，找不到返回 None
        try:
            match = next(search_root.rglob("version.json"))
            return str(match.absolute())
        except StopIteration:
            logging.warning(f"目录中未发现 version.json: {search_path}")
            return None

    def run_restore_env(self, version_json: str):
        """
        执行环境同步还原
        """
        args = ["-v", self.ctx.vehicle, "-p", version_json]
        return self._run_script("restore_env.sh", args)
