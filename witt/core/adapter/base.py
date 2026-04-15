from abc import ABC, abstractmethod
from typing import Union
from pathlib import Path


class BaseAdapter(ABC):
    """适配器抽象基类，定义执行通道必须实现的最小接口。"""

    def __init__(self, setup_env: str) -> None:
        self.setup_env = setup_env

    @abstractmethod
    def map_path(self, host_path: Union[str, Path]) -> str:
        """将宿主机路径转换为目标执行环境可识别的路径。"""
        pass

    @abstractmethod
    def execute(self, cmd: str) -> str:
        """非交互式执行命令并返回 stdout 字符串。"""
        pass

    def wrap_env(self, cmd: str) -> str:
        """为命令追加统一的运行时环境。"""
        base_env = "export LANG=C.UTF-8 && export LC_ALL=C.UTF-8"
        return f"{base_env} && source {self.setup_env} && {cmd}"

    def remove(self, path: str) -> None:
        """删除执行环境中的中间文件。"""
        pass

    def fetch_file(self, remote_path: str, local_dest: Path) -> None:
        """将执行环境中的文件拉取到宿主机。"""
        pass

    def execute_interactive(self, cmd: str) -> None:
        """交互式执行命令；默认退化为普通 execute。"""
        self.execute(cmd)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}>"
