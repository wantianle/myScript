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
        command_invocation = prompter.parse_command(raw_command)
        if command_invocation is None:
            continue
        if command_invocation.name == "quit":
            sys.exit(0)
        if command_invocation.name == "help":
            _handle_help_command(command_invocation)
            continue
        if command_invocation.name == "clear":
            _clear_screen()
            ui.print_banner()
            continue
        if command_invocation.name == "history" and _handle_history_subcommand(
            session,
            command_invocation,
        ):
            continue

        action = command_map.get(command_invocation.name)
        if action is None:
            ui.print_status("未知命令: {0}".format(raw_command), "WARN")
            ui.print_status("输入 help 查看可用命令", "WARN")
            continue

        try:
            action()
        except KeyboardInterrupt:
            ui.print_status("用户终止程序...", "WARN")
        except Exception as e:
            logging.error(f"执行命令 {command_invocation.name} 时发生异常: {e}")


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


def _handle_help_command(command_invocation: prompter.CommandInvocation) -> None:
    """处理 help 命令。"""
    if not command_invocation.args:
        ui.show_command_help(prompter.get_command_specs())
        return
    target_command_name = prompter.normalize_command(command_invocation.args[0])
    ui.show_command_help(
        prompter.get_command_specs(),
        target_command_name=target_command_name,
    )


def _handle_history_subcommand(
    session: AppSession,
    command_invocation: prompter.CommandInvocation,
) -> bool:
    """处理 history 命令下的轻量子命令。"""
    if not command_invocation.args:
        return False
    subcommand = command_invocation.args[0].lower()
    if subcommand == "clear":
        if not prompter.get_confirm_input("确认清空全部历史记录？"):
            return True
        session.replay_history_repository.clear()
        ui.print_status("已清空全部回播历史")
        return True
    if subcommand == "last":
        workflow.replay_workflow.replay_latest_history_entry(session)
        return True
    if subcommand.isdigit():
        workflow.replay_workflow.replay_history_by_index(session, int(subcommand))
        return True
    ui.print_status("不支持的 history 子命令: {0}".format(subcommand), "WARN")
    ui.print_status("当前支持: history clear | history last | history <序号>", "WARN")
    return True
