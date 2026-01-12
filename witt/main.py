import traceback
import subprocess
import sys
import cli
# import os
# root_path = os.path.dirname(os.path.abspath(__file__))
# if root_path not in sys.path:
#     sys.path.insert(0, root_path)

if __name__ == "__main__":
    try:
        cli.menu()
    except KeyboardInterrupt:
        sys.exit(0)
    # except subprocess.CalledProcessError as e:
    #     logging.error(
    #         f"命令执行失败: {' '.join(e.cmd if isinstance(e.cmd, list) else [e.cmd])}"
    #     )
    #     sys.exit(1)
    # except Exception as e:
    #     print(f"\n\033[1;31m[CRITICAL] 发生内部程序错误: {e}\033[0m")
    #     logging.debug("--- 捕获到未处理的 Python 异常堆栈 ---")
    #     logging.debug(e)
    #     sys.exit(1)
