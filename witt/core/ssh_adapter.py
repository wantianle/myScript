import subprocess
import logging


class SSHExecutor:
    def __init__(self, config):
        self.user = config["remote"]["user"]
        self.ip = config["remote"]["ip"]
        # 注意：远程车机的 setup.bash 路径可能与本地不同，建议在 YAML 中区分
        self.setup_bash = config["docker"]["setup_bash"]

    def execute(self, cmd: str) -> str:
        """通过 SSH 在远程车机执行命令"""
        # 同样注入 UTF-8 环境
        env_setup = "export LANG=C.UTF-8 && export LC_ALL=C.UTF-8 && export MDRIVE_ROOT_DIR='/mdrive' && export MDRIVE_DEP_DIR='/mdrive/mdrive_dep'"
        remote_cmd = f"{env_setup} && source {self.setup_bash} && {cmd}"

        # 构造 SSH 命令
        full_cmd = [
            "ssh",
            "-o",
            "ConnectTimeout=5",
            "-o",
            "StrictHostKeyChecking=no",
            f"{self.user}@{self.ip}",
            remote_cmd,
        ]

        try:
            result = subprocess.run(
                full_cmd, capture_output=True, text=True, check=True
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            error_detail = e.stderr.strip() or e.stdout.strip()
            logging.error(f"[SSH Exec Error] Command: {cmd}\nDetail: {error_detail}")
            raise RuntimeError(error_detail)
    def to_docker_path(self, host_path: str) -> str:
        """远程模式下通常不需要路径映射，直接返回原路径"""
        return str(host_path)
