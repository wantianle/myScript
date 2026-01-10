import logging
import traceback
import subprocess
import sys
from core.seesion import AppSession
from utils import cli
from utils import handles
from pathlib import Path

# ==================== 主菜单  ====================

def main_menu():
    while True:
        session = AppSession()
        config = session.config
        print("\n" + "=" * 50)
        print("               witt  v1.0")
        print("            What Is That Tag?")
        print("=" * 50)
        print("  1. 查询 -> 压缩/切片/下载 -> 同步/回放")
        print("  2. [仅查询] 查询 tag 对应 record 文件")
        print("  3. [仅压缩] 指定文件过滤 Channel")
        print("  4. [仅切片] 指定目录对时间切片")
        print("  5. [仅同步] 同步本地 docker 环境")
        print("  6. [仅回播] 查询并回播已处理数据")
        print("  h. [说明文档]")
        print("  q. 退出")
        print("=" * 50)
        choice = input("请选择操作: ").strip().lower()
        if choice == "1":
            cli.run_full_pipeline(session)
        elif choice in ("2", "3", "4", "5", "6"):
            cli.get_basic_info(config)
            if choice == "2":
                cli.get_workflow_params(config)
                session.task_query()
            elif choice == "3":
                target_path = Path(input("需要压缩的 record 文件完整路径: ").strip())
                session.task_compress(target_path)
                session.task_slice(target_path)
            elif choice == "4":
                cli.get_split_params(config)
                target = Path(input("需要切片的 record 文件的目录路径: ").strip())
                time_raw = input("基准时间 (HHMMSS): ").strip()
                tag_dt = handles.str_to_time(
                    f"{config['logic']['target_date'][:8]}{time_raw}"
                )
                for f in target.glob("*.record*"):
                    session.task_slice(f, tag_dt)
            elif choice == "5":
                config["logic"]["version_json"] = cli.get_json_input() or config["logic"][
                    "version_json"
                ]
                session.task_sync()
            elif choice == "6":
                print("\n>>> 进入数据回播...")
                config["host"]["dest_root"] = cli.get_user_input(
                    "请输入回播数据根目录(仅限/media下)", config["host"]["dest_root"]
                )
                cli.task_player_workflow(session)
        elif choice == "h":
            cli.usage()
        elif choice == "q":
            sys.exit(0)


if __name__ == "__main__":
    try:
        main_menu()
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
