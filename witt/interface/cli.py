import logging
import os
import sys
from typing import Callable, Dict

from . import prompter
from . import ui
from . import workflow
from core.session import AppSession


def menu() -> None:
    """运行第一阶段命令驱动 REPL 入口。"""
    session = AppSession()
    prompt_session = prompter.create_command_prompt_session()
    ui.print_banner()
    ui.print_status("输入 help 查看命令帮助，输入 quit 退出")

    command_map = _build_command_map(session)

    while True:
        raw_command = prompter.get_command_input(prompt_session)
        if raw_command is None:
            sys.exit(0)
        normalized_command = prompter.normalize_command(raw_command)
        if not normalized_command:
            continue
        if normalized_command == "quit":
            sys.exit(0)
        if normalized_command == "help":
            ui.show_command_help(prompter.get_command_specs())
            continue
        if normalized_command == "clear":
            _clear_screen()
            ui.print_banner()
            continue

        action = command_map.get(normalized_command)
        if action is None:
            ui.print_status("未知命令: {0}".format(raw_command), "WARN")
            ui.print_status("输入 help 查看可用命令", "WARN")
            continue

        try:
            action()
        except KeyboardInterrupt:
            ui.print_status("用户终止程序...", "WARN")
        except Exception as e:
            logging.error(f"执行命令 {normalized_command} 时发生异常: {e}")


def _build_command_map(session: AppSession) -> Dict[str, Callable[[], None]]:
    """构建标准命令到 workflow 动作的映射。"""
    return {
        "slice": lambda: workflow.slice_progress(session),
        "full": lambda: workflow.full_source_progress(session),
        "scan": lambda: workflow.auto_replay_progress(session),
        "manual": lambda: workflow.manual_replay_progress(session),
        "history": lambda: workflow.replay_history_progress(session),
        "traffic": lambda: workflow.traffic_light_replay_flow(session),
        "env": lambda: ui.show_environment_summary(session),
    }


def _clear_screen() -> None:
    """清空终端显示。"""
    os.system("clear")
