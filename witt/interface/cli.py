import logging
import sys
import questionary
from questionary import Choice

from . import ui
from . import workflow
from . import prompter
from core.session import AppSession


def menu():
    session = AppSession()
    choices = [
        Choice(title="[全流程] 查询 -> 切片 -> 回放", value="1"),
        Choice(title="[仅查询] 查询 tag 对应 record", value="2"),
        # Choice(title="[仅压缩] 指定文件过滤 Channel", value="3"),
        # Choice(title="[仅切片] 指定目录时间进行切片", value="4"),
        Choice(title="[仅同步] 同步本地 docker 环境", value="3"),
        Choice(title="[仅回播] 手动或者自动回播数据", value="4"),
        Choice(title="[进容器] 交互式进 docker bash", value="5"),
        Choice(title="[README] 使用说明", value="h"),
        Choice(title="[ 退出 ]", value="q"),
    ]
    menu_map = {
        "1": lambda: workflow.full_progress(session),
        "2": lambda: workflow.search_flow(session),
        # "3": lambda: workflow.compress_flow(session),
        # "4": lambda: workflow.slice_flow(session),
        "3": lambda: workflow.restore_env_flow(session),
        "4": lambda: workflow.play_flow(session),
        "5": lambda: session.runner.into_docker(),
        "h": lambda: prompter.usage(),
    }

    while True:
        ui.print_banner()
        choice = questionary.select(
            "请选择操作 :",
            choices=choices,
            use_shortcuts=True,
            style=questionary.Style(
                [
                    ("qmark", "fg:yellow bold"),  # 问号颜色
                    ("question", "bold"),  # 问题颜色
                    ("pointer", "fg:cyan bold"),  # 指针颜色
                    ("highlighted", "fg:cyan bold"),  # 选中项颜色
                    ("selected", "fg:green"),  # 确认项颜色
                ]
            ),
        ).ask()

        if choice is None or choice == "q":
            sys.exit(0)

        action = menu_map.get(choice)
        if action:
            try:
                action()
            except KeyboardInterrupt:
                ui.print_status("用户终止程序...", "WARN")
            except Exception as e:
                logging.error(f"执行操作 {choice} 时发生异常: {e}")
            input("按回车键继续...")
