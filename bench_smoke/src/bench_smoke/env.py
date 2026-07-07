"""台架运行时环境辅助函数。

提供统一的环境初始化入口，保证 mkit/vmc 在所有模块中正确解析。
"""

import os

# 环境初始化前缀：先 source .mdrive_vars.sh 设置 MDRIVE_ROOT_DIR，
# 再 source setup.sh 加载 mdrive 软件树环境变量。
_SHELL_INIT_PREFIX = (
    "source /mnt/ufs_data/project/.mdrive_vars.sh && "
    "source /mdrive/mdrive/setup.sh && "
)


def shell_init() -> str:
    """返回台架运行时环境的 shell 初始化命令前缀。

    可直接拼接到任何台架工具调用前：:

        cmd = env.shell_init() + "mkit info /path/to/file.mcap"
    """
    return _SHELL_INIT_PREFIX


# 已验证的 mkit 二进制绝对路径
_MKIT_BIN_ABSOLUTE = "/mnt/ufs_data/project/.vmc/softwares/mdrive/bin/mkit"


def mkit_bin() -> str:
    """返回 mkit 二进制路径。

    优先使用已验证的绝对路径，若文件不存在则回退到 "mkit"
    （依赖 shell_init 后的 PATH 解析）。本函数供本地调用方（如
    playback）使用；远程调用方应仅使用 shell_init()。
    """
    if os.path.isfile(_MKIT_BIN_ABSOLUTE):
        return _MKIT_BIN_ABSOLUTE
    return "mkit"
