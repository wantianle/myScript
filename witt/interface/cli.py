import logging
import os
import shlex
import subprocess
import sys
from shutil import which
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import prompter
from . import replay_workflow
from . import ui
from . import workflow
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
    _render_repl_home()

    while True:
        raw_command = prompter.get_command_input(prompt_session)
        if raw_command is None:
            sys.exit(0)
        command_invocation = prompter.parse_command(raw_command)
        if command_invocation is None:
            continue
        if not _validate_command_args(command_invocation):
            continue
        if command_invocation.name == "quit":
            sys.exit(0)
        if command_invocation.name == "help":
            _handle_help_command(command_invocation)
            continue
        if command_invocation.name == "config":
            session = _handle_config_command(session)
            continue
        if command_invocation.name == "clear":
            _clear_screen()
            _render_repl_home()
            continue
        if command_invocation.name == "history" and _handle_history_subcommand(
            session,
            command_invocation,
        ):
            continue

        command_map = _build_command_map(session)
        action = command_map.get(command_invocation.name)
        if action is None:
            ui.show_input_feedback(
                "未知命令: {0}".format(raw_command),
                hint="输入 help 查看可用命令",
            )
            continue

        try:
            action()
        except KeyboardInterrupt:
            ui.show_notice_section("命令执行", "用户终止程序", "WARN")
        except Exception as e:
            logging.error(f"执行命令 {command_invocation.name} 时发生异常: {e}")


def _render_repl_home() -> None:
    """渲染 REPL 启动页。"""
    ui.print_banner()


def _build_command_map(session: AppSession) -> Dict[str, Callable[[], None]]:
    """构建标准命令到 workflow 动作的映射。"""
    return {
        "slice": lambda: workflow.slice_progress(session),
        "replay": lambda: workflow.full_source_progress(session),
        "scan": lambda: workflow.auto_replay_progress(session),
        "manual": lambda: workflow.manual_replay_progress(session),
        "history": lambda: workflow.replay_history_progress(session),
        "traffic": lambda: replay_workflow.traffic_light_replay_flow(session),
        "env": lambda: ui.show_environment_summary(session),
    }


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
        editor_command = _split_command_text(editor_text)
        if editor_command and which(editor_command[0]) is not None:
            return editor_command
    for editor_name in ("nano", "vim", "vi"):
        editor_path = which(editor_name)
        if editor_path is not None:
            return [editor_path]
    return None


def _split_command_text(command_text: str) -> List[str]:
    """解析环境变量中的编辑器命令。"""
    try:
        return shlex.split(command_text)
    except ValueError:
        return command_text.split()


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
        ui.show_notice_section(
            "历史命令",
            "已清空全部回播历史",
        )
        return True
    if subcommand == "last":
        replay_workflow.replay_latest_history_entry(session)
        return True
    if subcommand.isdigit():
        replay_workflow.replay_history_by_index(session, int(subcommand))
        return True
    ui.show_result_section(
        "历史命令",
        "不支持的 history 子命令: {0}".format(subcommand),
        "WARN",
        details=["当前支持: history clear | history last | history <序号>"],
        next_step="使用 help history 查看命令说明",
    )
    return True
