import sys
from core.session import AppSession
import parser
from datetime import datetime
from pathlib import Path
import ui
import workflow


def menu():
    session = AppSession()
    while True:
        ui.print_banner()
        ui.print_menu()

        choice = input("请选择操作: ").strip().lower()

        if choice == "1":
            parser.get_basic_params(session.ctx.config)
            parser.get_path_params(session.ctx.config)
            workflow.full_progress(session)

        elif choice in ("2", "4", "6"):
            parser.get_basic_params(session.ctx.config)

            if choice == "2":
                parser.get_path_params(session.ctx.config)
                session.record_query()

            elif choice == "4":
                parser.get_split_params(session.ctx.config)
                target = Path(input("需要切片的 record 文件的目录路径: ").strip())
                time_raw = input("基准时间 (HHMMSS): ").strip()
                tag_dt = datetime.strptime(f"{session.ctx.target_date[:8]}{time_raw}", "%Y%m%d%H%M%S")
                for f in target.glob("*.record*"):
                    session.record_slice(f, tag_dt)

            elif choice == "6":
                print("\n>>> 进入数据回播...")
                session.ctx.config["host"]["dest_root"] = parser.get_user_input(
                    "请输入回播数据根目录(仅限/media下)",
                    session.ctx.config["host"]["dest_root"],
                )
                workflow.playflow(session)

        elif choice == "3":
            target_path = Path(input("需要压缩的 record 文件完整路径: ").strip())
            blacklist = parser.select_channels_interactive(session.recorder, target_path)
            session.record_compress(target_path, blacklist)

        elif choice == "5":
            session.ctx.config["logic"]["version_json"] = (
                parser.get_json_input() or session.ctx.config["logic"]["version_json"]
            )
            session.restore_env()

        elif choice == "h":
            parser.usage()

        elif choice == "q":
            sys.exit(0)
