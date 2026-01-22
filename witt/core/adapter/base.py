from abc import ABC, abstractmethod
from typing import Union
from pathlib import Path

class BaseAdapter(ABC):
    """
    适配器抽象基类，定义所有执行通道必须实现的接口
    """
    def __init__(self, setup_env: str) -> None:
        self.setup_env = setup_env

    def wrap_env(self, cmd: str) -> str:
        """统一包装环境变量"""
        base_env = "export LANG=C.UTF-8 && export LC_ALL=C.UTF-8"
        return f"{base_env} && source {self.setup_env} && {cmd}"

    @abstractmethod
    def get_size(self, path: str) -> int:
        """获取执行环境中文件的大小"""
        return 0

    @abstractmethod
    def remove(self, path: str) -> None:
        """删除执行环境中的中间文件"""
        pass

    @abstractmethod
    def fetch_file(self, remote_path: str, local_dest: Path) -> None:
        """将执行环境中的文件拉取到宿主机。本地/Docker模式下通常是 move 或 pass"""
        pass

    @abstractmethod
    def map_path(self, host_path: Union[str, Path]) -> str:
        """
        将本地/宿主机路径转换为执行环境（Docker内或远程车机）可识别的路径
        """
        pass

    @abstractmethod
    def execute(self, cmd: str) -> str:
        """
        非交互式执行命令，返回 stdout 字符串
        """
        pass

    def execute_interactive(self, cmd: str, scriptRunner) -> None:
        """
        可选实现：交互式执行（如回放数据），默认调用普通 execute
        如果子类需要特殊处理（如 docker -it），则重写此方法
        """
        self.execute(cmd)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}>"
