from abc import ABC, abstractmethod
from typing import Union
from pathlib import Path

class BaseAdapter(ABC):
    """
    适配器抽象基类，定义所有执行通道必须实现的接口
    """
    def __init__(self, setup_env: str):
        self.setup_env = setup_env

    def wrap_env(self, cmd: str) -> str:
        """统一包装环境变量"""
        base_env = "export LANG=C.UTF-8 && export LC_ALL=C.UTF-8"
        return f"{base_env} && source {self.setup_env} && {cmd}"

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

    def execute_interactive(self, cmd: str):
        """
        可选实现：交互式执行（如回放数据），默认调用普通 execute
        如果子类需要特殊处理（如 docker -it），则重写此方法
        """
        return self.execute(cmd)

    def __repr__(self):
        return f"<{self.__class__.__name__}>"
