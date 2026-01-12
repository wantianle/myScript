import logging
import sys
from core.session import AppSession
import parser
from utils import handles
from pathlib import Path

import workflow

def menu():
    while True:
        session = AppSession()
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
            workflow.full_progress(session)
        elif choice in ("2", "3", "4", "5", "6"):
            parser.get_basic_params(session.ctx.config)
            if choice == "2":
                parser.get_path_params(session.ctx.config)
                session.record_query()
            elif choice == "3":
                target_path = Path(input("需要压缩的 record 文件完整路径: ").strip())
                session.record_compress(target_path)
                session.record_slice(target_path)
            elif choice == "4":
                parser.get_split_params(session.ctx.config)
                target = Path(input("需要切片的 record 文件的目录路径: ").strip())
                time_raw = input("基准时间 (HHMMSS): ").strip()
                tag_dt = handles.str_to_time(f"{session.ctx.target_date[:8]}{time_raw}")
                for f in target.glob("*.record*"):
                    session.record_slice(f, tag_dt)
            elif choice == "5":
                session.ctx.config["logic"]["version_json"] = (
                    parser.get_json_input()
                    or session.ctx.config["logic"]["version_json"]
                )
                session.task_sync()
            elif choice == "6":
                print("\n>>> 进入数据回播...")
                session.ctx.config["host"]["dest_root"] = parser.get_user_input(
                    "请输入回播数据根目录(仅限/media下)",
                    session.ctx.config["host"]["dest_root"],
                )
                session.task_play()
        elif choice == "h":
            parser.usage()
        elif choice == "q":
            sys.exit(0)
