import subprocess
import sys
import importlib.util


class EnvironmentManager:
    """环境自动化配置类，负责检查 pip 及项目依赖"""

    # 定义依赖映射: (pip安装名, Python导入名)
    DEPENDENCIES = [
        ("pyyaml", "yaml"),
        ("alive-progress", "alive_progress"),
    ]

    # 国内镜像源（清华大学）
    PYPI_INDEX = "https://pypi.tuna.tsinghua.edu.cn/simple"

    @classmethod
    def ensure_pip(cls):
        """确保系统安装了 pip，如果没有则尝试自动修复"""
        if importlib.util.find_spec("pip") is not None:
            return True

        print(">>> 未检测到 pip，正在尝试紧急引导 (ensurepip)...")
        try:
            # 1. 尝试使用内置 ensurepip
            subprocess.check_call(
                [sys.executable, "-m", "ensurepip", "--default-pip"],
                stdout=subprocess.DEVNULL,
            )
            # 2. 尝试升级 pip 到最新版
            subprocess.check_call(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--upgrade",
                    "pip",
                    "-i",
                    cls.PYPI_INDEX,
                ],
                stdout=subprocess.DEVNULL,
            )
            print(">>> pip 安装/修复成功！")
            return True
        except Exception:
            print("错误: 系统缺少 pip 且自动修复失败。")
            print("请执行以下命令手动安装 pip 后重试:")
            print("   sudo apt update && sudo apt install python3-pip")
            return False

    @classmethod
    def install_missing(cls):
        """检查并安装缺失的库"""
        missing_for_pip = []

        for pkg_name, import_name in cls.DEPENDENCIES:
            try:
                __import__(import_name)
            except ImportError:
                missing_for_pip.append(pkg_name)

        if missing_for_pip:
            print(f">>> 检测到依赖缺失，正在自动安装: {', '.join(missing_for_pip)}")
            try:
                subprocess.check_call(
                    [
                        sys.executable,
                        "-m",
                        "pip",
                        "install",
                        *missing_for_pip,
                        "-i",
                        cls.PYPI_INDEX,
                    ]
                )
                print(">>> 所有依赖已就绪！\n")
            except Exception as e:
                print(
                    f"❌ 自动安装失败，请手动执行: pip install {' '.join(missing_for_pip)}"
                )
                print(f"错误详情: {e}")
                return False
        return True

    @classmethod
    def bootstrap(cls):
        """一键引导入口"""
        if not cls.ensure_pip():
            sys.exit(1)
        if not cls.install_missing():
            sys.exit(1)
