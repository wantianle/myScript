import logging
import os
import shlex
import subprocess
import sys
from shutil import which
from pathlib import Path
from typing import List, Optional

from . import prompter
from . import ui
from . import workflow
from . import workflow_replay
from core.session import AppSession

INTENT_ONLY_COMMANDS = {
    "config",
    "slice",
    "replay",
    "scan",
    "manual",
    "traffic",
    "env",
    "clear",
    "quit",
}


def menu() -> None:
    """运行第一阶段命令驱动 REPL 入口。"""
    session = AppSession()
    prompt_session = prompter.create_command_prompt_session()
    ui.print_banner()

    while True:
        try:
            raw_command = prompt_session.prompt("Witt > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)
        command_invocation = prompter.parse_command(raw_command)
        if command_invocation is None:
            continue
        if not _validate_command_args(command_invocation):
            continue
        if command_invocation.name == "quit":
            sys.exit(0)
        if command_invocation.name == "help":
            if not command_invocation.args:
                ui.show_command_help(prompter.COMMAND_SPECS)
            else:
                ui.show_command_help(
                    prompter.COMMAND_SPECS,
                    target_command_name=prompter.normalize_command(
                        command_invocation.args[0]
                    ),
                )
            continue
        if command_invocation.name == "config":
            session = _handle_config_command(session)
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
        action_map = {
            "slice": workflow.slice_progress,
            "replay": workflow.full_source_progress,
            "scan": workflow.auto_replay_progress,
            "manual": workflow.manual_replay_progress,
            "history": workflow.replay_history_progress,
            "traffic": workflow_replay.traffic_light_replay_flow,
            "env": ui.show_environment_summary,
        }
        action = action_map.get(command_invocation.name)
        if action is None:
            ui.show_input_feedback(
                "未知命令: {0}".format(raw_command),
                hint="输入 help 查看可用命令",
            )
            continue

        try:
            action(session)
        except KeyboardInterrupt:
            ui.show_notice_section("命令执行", "用户终止程序", "WARN")
        except Exception as e:
            logging.error(f"执行命令 {command_invocation.name} 时发生异常: {e}")


def _validate_command_args(command_invocation: prompter.CommandInvocation) -> bool:
    """校验命令参数是否符合当前意图型入口约束。"""
    if (
        command_invocation.name in INTENT_ONLY_COMMANDS
        and command_invocation.args
    ):
        ui.show_input_feedback(
            "{0} 不接受参数，请直接输入 {0}".format(command_invocation.name),
        )
        return False
    if command_invocation.name == "help" and len(command_invocation.args) > 1:
        ui.show_input_feedback("help 仅支持: help 或 help <command>")
        return False
    if command_invocation.name == "history" and len(command_invocation.args) > 1:
        ui.show_input_feedback(
            "history 仅支持: history | history clear | history last | history <序号>",
        )
        return False
    return True


def _clear_screen() -> None:
    """清空终端显示。"""
    os.system("clear")


def _handle_config_command(session: AppSession) -> AppSession:
    """打开配置文件并在退出编辑器后重建当前会话。"""
    config_path = session.ctx.config_path
    ui.show_progress_section(
        "配置编辑",
        "打开用户配置文件",
        details=[str(config_path)],
        hint="编辑完成后会尝试重建当前会话",
    )
    if not _open_in_editor(config_path):
        return session
    try:
        reloaded_session = AppSession(config_path=config_path)
    except Exception as e:
        ui.show_result_section(
            "配置编辑",
            "配置重载失败，继续沿用旧会话",
            "ERROR",
            details=[str(e)],
            next_step="检查 settings.yaml 格式后重新执行 config",
        )
        return session
    ui.show_notice_section(
        "配置编辑",
        "配置编辑已结束，已重建当前会话配置",
    )
    return reloaded_session


def _open_in_editor(config_path: Path) -> bool:
    """使用终端编辑器打开配置文件。"""
    editor_command = _resolve_editor_command()
    if editor_command is None:
        ui.show_result_section(
            "配置编辑",
            "未找到可用编辑器",
            "ERROR",
            details=["请设置 $EDITOR 或安装 nano/vim"],
            next_step="配置终端编辑器后重新执行 config",
        )
        return False
    try:
        return_code = subprocess.call(editor_command + [str(config_path)])
    except OSError as e:
        ui.show_result_section(
            "配置编辑",
            "打开配置文件失败",
            "ERROR",
            details=[str(e)],
            next_step="检查编辑器命令和文件权限后重试",
        )
        return False
    if return_code != 0:
        ui.show_result_section(
            "配置编辑",
            "编辑器异常退出，未重建会话配置",
            "WARN",
            next_step="修正编辑器问题后重新执行 config",
        )
        return False
    return True


def _resolve_editor_command() -> Optional[List[str]]:
    """按 VISUAL/EDITOR/常见终端编辑器顺序解析编辑器命令。"""
    for env_name in ("VISUAL", "EDITOR"):
        editor_text = os.environ.get(env_name, "").strip()
        if not editor_text:
            continue
        try:
            editor_command = shlex.split(editor_text)
        except ValueError:
            editor_command = editor_text.split()
        if editor_command and which(editor_command[0]) is not None:
            return editor_command
    for editor_name in ("nano", "vim", "vi"):
        editor_path = which(editor_name)
        if editor_path is not None:
            return [editor_path]
    return None


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
        session.replay_history_repository.save([])
        ui.show_notice_section(
            "历史命令",
            "已清空全部回播历史",
        )
        return True
    if subcommand == "last":
        workflow_replay.replay_latest_history_entry(session)
        return True
    if subcommand.isdigit():
        workflow_replay.replay_history_by_index(session, int(subcommand))
        return True
    ui.show_result_section(
        "历史命令",
        "不支持的 history 子命令: {0}".format(subcommand),
        "WARN",
        details=["当前支持: history clear | history last | history <序号>"],
        next_step="使用 help history 查看命令说明",
    )
    return True
