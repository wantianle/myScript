import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, TypeVar

import questionary
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory
from questionary import Choice

from interface import ui

TaskLike = TypeVar("TaskLike")


@dataclass(frozen=True)
class CommandSpec:
    name: str
    aliases: List[str]
    summary: str
    example: str


@dataclass(frozen=True)
class CommandInvocation:
    name: str
    args: List[str]
    raw: str


MAIN_MENU_ITEMS = [
    ("[切片模式] 查询 -> 切片 -> 回播", "1"),
    ("[全量模式] 查询 -> 回播", "2"),
    ("[自动回播] 自动扫描回播", "3"),
    ("[手动回播] 手动选择回播", "4"),
    ("[回灌红绿灯] 回灌红绿灯", "5"),
    ("[历史回播] 浏览并回播历史记录", "6"),
]

MAIN_MENU_STYLE = questionary.Style(
    [
        ("qmark", "fg:yellow bold"),
        ("question", "bold"),
        ("pointer", "fg:cyan bold"),
        ("highlighted", "fg:cyan bold"),
        ("selected", "fg:green"),
    ]
)

COMMAND_SPECS = [
    CommandSpec("help", ["h", "?"], "显示命令帮助", "help"),
    CommandSpec("set", ["cfg"], "设置会话默认参数", "set date 20260418"),
    CommandSpec("slice", ["s"], "查询、切片并可选回播", "slice"),
    CommandSpec("full", ["f"], "全量模式查询后直接回播", "full"),
    CommandSpec("scan", ["auto", "a"], "扫描回播目录并回播", "scan"),
    CommandSpec("manual", ["m"], "手动拖包回播", "manual"),
    CommandSpec("history", ["his"], "浏览历史并回播", "history"),
    CommandSpec("traffic", ["tl"], "红绿灯回灌模式", "traffic"),
    CommandSpec("env", ["e"], "查看当前环境摘要", "env"),
    CommandSpec("clear", ["cls"], "清空当前终端显示", "clear"),
    CommandSpec("quit", ["q", "exit"], "退出工具", "quit"),
]


def build_command_alias_map() -> dict:
    """构建命令名与别名到标准命令的映射。"""
    alias_map = {}
    for command_spec in COMMAND_SPECS:
        alias_map[command_spec.name] = command_spec.name
        for alias in command_spec.aliases:
            alias_map[alias] = command_spec.name
    return alias_map


def create_command_prompt_session() -> PromptSession:
    """创建命令行 REPL 会话。"""
    history_path = Path.home() / ".witt" / "command_history"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    completer_words = []
    for command_spec in COMMAND_SPECS:
        completer_words.append(command_spec.name)
        completer_words.extend(command_spec.aliases)
    command_completer = WordCompleter(
        sorted(set(completer_words)),
        ignore_case=True,
        sentence=True,
    )
    return PromptSession(
        history=FileHistory(str(history_path)),
        completer=command_completer,
        auto_suggest=AutoSuggestFromHistory(),
        bottom_toolbar=_build_command_toolbar,
    )


def get_command_input(prompt_session: PromptSession) -> Optional[str]:
    """读取一条命令输入。"""
    try:
        command_text = prompt_session.prompt("Witt > ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    return command_text


def normalize_command(command_text: str) -> str:
    """将原始命令映射到标准命令名。"""
    command_parts = command_text.strip().split()
    if not command_parts:
        return ""
    alias_map = build_command_alias_map()
    return alias_map.get(command_parts[0].lower(), command_parts[0].lower())


def parse_command(command_text: str) -> Optional[CommandInvocation]:
    """将原始输入解析为标准命令和参数列表。"""
    raw_text = command_text.strip()
    if not raw_text:
        return None
    command_parts = raw_text.split()
    return CommandInvocation(
        name=normalize_command(command_parts[0]),
        args=command_parts[1:],
        raw=raw_text,
    )


def get_command_specs() -> List[CommandSpec]:
    """返回命令定义列表。"""
    return list(COMMAND_SPECS)


def find_command_spec(command_name: str) -> Optional[CommandSpec]:
    """按标准命令名查找命令定义。"""
    for command_spec in COMMAND_SPECS:
        if command_spec.name == command_name:
            return command_spec
    return None


def find_command_spec(command_name: str) -> Optional[CommandSpec]:
    """按标准命令名查找命令定义。"""
    for command_spec in COMMAND_SPECS:
        if command_spec.name == command_name:
            return command_spec
    return None


def _build_command_toolbar() -> str:
    """构建 REPL 底部快捷提示。"""
    return " help  slice  full  scan  manual  history  traffic  env  clear  quit "


def get_user_input(prompt: str, default_value: str) -> str:
    """读取带默认值的单行文本输入。"""
    try:
        val = input(f"\033[32m{prompt}\033[0m (默认 {default_value}): ").strip()
        return val if val else default_value
    except KeyboardInterrupt:
        print()
        raise


def get_int_input(prompt: str, default_value) -> int:
    """读取整数输入，直到用户提供合法整数。"""
    while True:
        raw_val = get_user_input(prompt, str(default_value))
        try:
            return int(raw_val)
        except ValueError:
            ui.print_status("请输入整数", "WARN")


def choose_option(
    prompt: str,
    options: Sequence[str],
    index: bool = False,
    default_index: int = 0,
):
    """显示简易选项列表并返回选中值或索引。"""
    for i, opt in enumerate(options, 1):
        print(f"[{i}] {opt}  ", end="")
    while True:
        if default_index and 1 <= default_index <= len(options):
            prompt_suffix = " (默认 {0})".format(default_index)
        else:
            prompt_suffix = ""
        val = input(f"\033[32m{prompt}{prompt_suffix}: \033[0m").strip()
        if not val and default_index and 1 <= default_index <= len(options):
            return default_index if index else options[default_index - 1]
        if val.isdigit() and 1 <= int(val) <= len(options):
            return int(val) if index else options[int(val) - 1]
        ui.print_status("输入无效，请重新选择", "WARN")


def get_selected_indices(
    all_tasks: Sequence[TaskLike],
    prompt: str = "请输入要处理的序号",
) -> List[TaskLike]:
    """根据用户输入的序号表达式返回选中的任务对象列表。"""
    total_count = len(all_tasks)
    if total_count == 0:
        ui.print_status("任务列表为空", "ERROR")
        return []

    while True:
        raw_input = input(f"{prompt}\n单选 1,3,5 | 多选 2-6 | 反选 0 5 7-15 | 全选 0: ").strip()
        clean_input = re.sub(r"[^\d\-,\s\n]", "", raw_input)
        tokens = [t for t in re.split(r"[,\s\n]+", clean_input) if t]
        if not tokens:
            ui.print_status("输入为空，请重新输入", "WARN")
            continue

        full_set = set(range(1, total_count + 1))
        result_set = set()
        is_exclude_mode = tokens[0] == "0"
        if is_exclude_mode:
            result_set = full_set.copy()
            tokens = tokens[1:]
        for token in tokens:
            try:
                if "-" in token and not token.startswith("-"):
                    parts = token.split("-")
                    start, end = int(parts[0]), int(parts[1])
                    scope = set(range(min(start, end), max(start, end) + 1))
                    if is_exclude_mode:
                        result_set -= scope
                    else:
                        result_set |= scope
                else:
                    val = abs(int(token))
                    if is_exclude_mode:
                        result_set.discard(val)
                    else:
                        result_set.add(val)
            except (ValueError, IndexError):
                ui.print_status("输入无效，请重新输入", "WARN")
                continue
        final_ids = sorted([i for i in result_set if 1 <= i <= total_count])
        if not final_ids:
            ui.print_status("未选中任何有效序号，请检查输入", "ERROR")
            continue

        preview_limit = 10
        display_ids = final_ids[:preview_limit]
        preview_str = ", ".join(map(str, display_ids))
        if len(final_ids) > preview_limit:
            preview_str += " ..."
        ui.print_status(f"选中待处理序号: [{preview_str}(共 {len(final_ids)} 项)]")
        if get_confirm_input("确认执行？", True):
            return [all_tasks[i - 1] for i in final_ids]
        ui.print_status("已取消...", "WARN")


def get_confirm_input(prompt: str, default: bool = False) -> bool:
    """通用的二次确认函数"""
    suffix = "[Y/n]" if default else "[y/N]"
    res = input(f"{prompt} {suffix} (回车 {'Y' if default else 'N'}): ").strip().lower()
    if not res:
        return default
    return res == "y"


def select_main_menu_action() -> Optional[str]:
    """显示主菜单并返回用户选择的动作编号。"""
    menu_choices = [
        Choice(title=title, value=value)
        for title, value in MAIN_MENU_ITEMS
    ]
    return questionary.select(
        "请选择操作 :",
        choices=menu_choices,
        use_shortcuts=True,
        style=MAIN_MENU_STYLE,
    ).ask()


def wait_for_continue() -> None:
    """等待用户确认后继续回到主菜单。"""
    try:
        input("按回车键继续...")
    except KeyboardInterrupt:
        print()
