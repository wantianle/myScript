import logging
import sys

from . import prompter
from . import ui
from . import workflow
from core.session import AppSession


def menu() -> None:
    """显示主菜单并分发用户选择的动作。"""
    session = AppSession()

    while True:
        ui.print_banner()
        menu_map = {
            "1": lambda: workflow.full_progress(session),
            # "2": lambda: workflow.search_flow(session),
            # "3": lambda: workflow.compress_flow(session),
            # "4": lambda: workflow.slice_flow(session),
            "2": lambda: workflow.replay_flow(session),
            "3": lambda: workflow.restore_environment_flow(session),
            "4": lambda: session.runner.into_docker(),
            "5": lambda: workflow.traffic_light_replay_flow(session),
        }
        choice = prompter.select_main_menu_action()

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
            prompter.wait_for_continue()
