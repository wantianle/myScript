import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Sequence, TypeVar

from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import PathCompleter, WordCompleter
from prompt_toolkit.history import FileHistory

from interface import ui

TaskLike = TypeVar("TaskLike")
_PROMPT_SESSION_CACHE = {}
_COMMAND_TOOLBAR_TEXT = " help  config  slice  replay  scan  manual  history  traffic  env  clear  quit "
_INPUT_TOOLBAR_TEXT = " Enter 确认  Tab 补全  Ctrl+R 历史 "


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

COMMAND_SPECS = [
    CommandSpec("help", ["h", "?"], "显示命令帮助", "help history"),
    CommandSpec("config", ["cfg"], "编辑用户 settings.yaml 并重建会话配置", "config"),
    CommandSpec("slice", ["s"], "查询、切片并可选回播", "slice"),
    CommandSpec("replay", ["r"], "查询后执行原始数据回放（不切片）", "replay"),
    CommandSpec("scan", ["a"], "扫描本地回放目录后浏览并回放", "scan"),
    CommandSpec("manual", ["m"], "直接拖拽或输入 record 文件/目录回放", "manual"),
    CommandSpec("history", ["his"], "浏览历史并支持少量子命令", "history last"),
    CommandSpec("traffic", ["tl"], "红绿灯回灌模式", "traffic"),
    CommandSpec("env", ["e"], "查看当前环境摘要", "env"),
    CommandSpec("clear", ["cls"], "清空当前终端显示", "clear"),
    CommandSpec("quit", ["q", "exit"], "退出工具", "quit"),
]
_COMMAND_ALIAS_MAP = {
    alias: command_spec.name
    for command_spec in COMMAND_SPECS
    for alias in [command_spec.name] + command_spec.aliases
}


def create_command_prompt_session() -> PromptSession:
    """创建命令行 REPL 会话。"""
    history_path = Path.home() / ".witt" / "command_history"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    completer_words = []
    for command_spec in COMMAND_SPECS:
        completer_words.append(command_spec.name)
        completer_words.extend(command_spec.aliases)
    command_completer = WordCompleter(
        _sort_completion_words(completer_words),
        ignore_case=True,
        sentence=True,
    )
    return PromptSession(
        history=FileHistory(str(history_path)),
        completer=command_completer,
        auto_suggest=AutoSuggestFromHistory(),
        bottom_toolbar=_COMMAND_TOOLBAR_TEXT,
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
    command_name = command_parts[0].lower()
    return _COMMAND_ALIAS_MAP.get(command_name, command_name)


def parse_command(command_text: str) -> Optional[CommandInvocation]:
    """将原始输入解析为标准命令和参数列表。"""
    raw_text = command_text.strip()
    if not raw_text:
        return None
    try:
        command_parts = shlex.split(raw_text)
    except ValueError:
        command_parts = raw_text.split()
    return CommandInvocation(
        name=normalize_command(command_parts[0]),
        args=command_parts[1:],
        raw=raw_text,
    )


def get_command_specs() -> List[CommandSpec]:
    """返回命令定义列表。"""
    return list(COMMAND_SPECS)


def _sort_completion_words(words: Sequence[object]) -> List[str]:
    """按自然数字顺序整理补全词。"""
    normalized_words = sorted(
        {str(word) for word in words},
        key=_completion_sort_key,
    )
    return normalized_words


def _completion_sort_key(word: str):
    """生成自然排序 key，使数字按数值顺序排列。"""
    parts = re.split(r"(\d+)", word)
    key = []
    for part in parts:
        if not part:
            continue
        if part.isdigit():
            key.append((0, int(part)))
        else:
            key.append((1, part.lower()))
    return key


def _get_prompt_session(history_name: str) -> PromptSession:
    """按历史分类复用 PromptSession。"""
    prompt_session = _PROMPT_SESSION_CACHE.get(history_name)
    if prompt_session is not None:
        return prompt_session
    history_path = Path.home() / ".witt" / "history" / "{0}.txt".format(history_name)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_session = PromptSession(
        history=FileHistory(str(history_path)),
        auto_suggest=AutoSuggestFromHistory(),
    )
    _PROMPT_SESSION_CACHE[history_name] = prompt_session
    return prompt_session


def prompt_text(
    prompt: str,
    default_value: str = "",
    history_name: str = "general",
    completer_words: Optional[Sequence[str]] = None,
    path_completion: bool = False,
) -> str:
    """统一的单行输入适配，提供历史、补全和可编辑默认值。"""
    prompt_session = _get_prompt_session(history_name)
    completer = None
    if completer_words:
        completer = WordCompleter(
            _sort_completion_words(completer_words),
            ignore_case=True,
            sentence=True,
        )
    elif path_completion:
        completer = PathCompleter(expanduser=True)
    try:
        return prompt_session.prompt(
            prompt + ": ",
            default=default_value,
            completer=completer,
            complete_while_typing=False,
            bottom_toolbar=_INPUT_TOOLBAR_TEXT,
        ).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise


def get_user_input(
    prompt: str,
    default_value: str,
    history_name: str = "text",
    path_completion: bool = False,
) -> str:
    """读取带默认值的单行文本输入。"""
    val = prompt_text(
        prompt,
        default_value,
        history_name=history_name,
        path_completion=path_completion,
    )
    return val if val else default_value


def get_int_input(prompt: str, default_value, history_name: str = "int") -> int:
    """读取整数输入，直到用户提供合法整数。"""
    while True:
        raw_val = get_user_input(
            prompt,
            str(default_value),
            history_name=history_name,
        )
        try:
            return int(raw_val)
        except ValueError:
            ui.show_input_feedback("请输入整数")


def choose_option(
    prompt: str,
    options: Sequence[str],
    index: bool = False,
    default_index: int = 0,
):
    """显示简易选项列表并返回选中值或索引。"""
    while True:
        ui.show_option_choices(
            "选项列表",
            prompt,
            options,
            default_index=default_index,
        )
        default_value = (
            str(default_index)
            if default_index and 1 <= default_index <= len(options)
            else ""
        )
        completer_words = [str(i) for i in range(1, len(options) + 1)] + list(options)
        val = prompt_text(
            prompt,
            default_value,
            history_name="option",
            completer_words=completer_words,
        )
        if not val and default_index and 1 <= default_index <= len(options):
            return default_index if index else options[default_index - 1]
        if val.isdigit() and 1 <= int(val) <= len(options):
            return int(val) if index else options[int(val) - 1]
        for option_index, option_text in enumerate(options, 1):
            if val.lower() == option_text.lower():
                return option_index if index else option_text
        ui.show_input_feedback(
            "输入无效，请重新选择",
            hint="可输入序号或候选项名称",
        )


def resolve_filter_keyword(raw_input: str) -> Optional[str]:
    """解析 `/关键字` 形式的筛选输入。"""
    if not raw_input.startswith("/"):
        return None
    return raw_input[1:].strip()


def matches_search_keyword(keyword: str, values: Sequence[object]) -> bool:
    """判断关键字是否命中给定字段集合。"""
    normalized_keyword = keyword.strip().lower()
    if not normalized_keyword:
        return True
    searchable_text = " ".join(str(value) for value in values).lower()
    return all(token in searchable_text for token in normalized_keyword.split())


def parse_index_expression(raw_input: str, total_count: int) -> List[int]:
    """解析序号表达式并返回 1-based 序号列表。"""
    clean_input = re.sub(r"[^\d\-,\s\n]", "", raw_input)
    tokens = [token for token in re.split(r"[,\s\n]+", clean_input) if token]
    if not tokens:
        return []

    full_set = set(range(1, total_count + 1))
    result_set = set()
    is_exclude_mode = tokens[0] == "0"
    if is_exclude_mode:
        result_set = full_set.copy()
        tokens = tokens[1:]
    for token in tokens:
        if "-" in token and not token.startswith("-"):
            parts = token.split("-")
            if len(parts) != 2:
                raise ValueError("invalid range token")
            start = int(parts[0])
            end = int(parts[1])
            scope = set(range(min(start, end), max(start, end) + 1))
            if is_exclude_mode:
                result_set -= scope
            else:
                result_set |= scope
            continue
        value = abs(int(token))
        if is_exclude_mode:
            result_set.discard(value)
        else:
            result_set.add(value)

    return sorted(index for index in result_set if 1 <= index <= total_count)


def get_selected_indices(
    all_tasks: Sequence[TaskLike],
    prompt: str = "请输入要处理的序号",
    render_items: Optional[Callable[[Sequence[TaskLike], str, int], None]] = None,
    search_values_getter: Optional[Callable[[TaskLike], Sequence[object]]] = None,
    history_name: str = "task_selection",
) -> List[TaskLike]:
    """根据用户输入的序号表达式返回选中的任务对象列表。"""
    total_count = len(all_tasks)
    if total_count == 0:
        ui.show_result_section(
            "选择列表",
            "任务列表为空",
            "ERROR",
            next_step="请先准备可选数据后重试",
        )
        return []

    current_tasks = list(all_tasks)
    search_keyword = ""
    while True:
        if render_items is not None:
            render_items(current_tasks, search_keyword, total_count)
        raw_input = prompt_text(
            "{0}\n单选 1,3,5 | 多选 2-6 | 反选 0 5 7-15 | 全选 0"
            " | /关键字筛选 | / 清空筛选 | 回车返回".format(prompt),
            history_name=history_name,
        )
        if not raw_input.strip():
            return []
        filter_keyword = resolve_filter_keyword(raw_input)
        if filter_keyword is not None:
            if search_values_getter is None:
                ui.show_input_feedback("当前列表不支持关键字筛选")
                continue
            next_tasks = [
                task
                for task in all_tasks
                if matches_search_keyword(filter_keyword, search_values_getter(task))
            ]
            search_keyword = filter_keyword
            current_tasks = next_tasks if filter_keyword else list(all_tasks)
            continue
        if not current_tasks:
            ui.show_input_feedback(
                "当前筛选结果为空",
                hint="请调整关键字或输入 / 清空筛选",
            )
            continue
        try:
            final_ids = parse_index_expression(raw_input, len(current_tasks))
        except ValueError:
            ui.show_input_feedback(
                "输入无效，请重新输入",
                hint="支持单选、多选、反选和范围表达式",
            )
            continue
        if not final_ids:
            ui.show_input_feedback(
                "未选中任何有效序号，请检查输入",
                "ERROR",
            )
            continue

        preview_limit = 10
        display_ids = final_ids[:preview_limit]
        preview_str = ", ".join(map(str, display_ids))
        if len(final_ids) > preview_limit:
            preview_str += " ..."
        ui.show_notice_section(
            "选择确认",
            "选中待处理序号: [{0}(共 {1} 项)]".format(
                preview_str,
                len(final_ids),
            ),
        )
        if get_confirm_input("确认执行？", True):
            return [current_tasks[i - 1] for i in final_ids]
        ui.show_input_feedback("已取消", "WARN")


def get_confirm_input(prompt: str, default: bool = False) -> bool:
    """通用的二次确认函数。"""
    suffix = "[Y/n]" if default else "[y/N]"
    default_value = "y" if default else "n"
    res = prompt_text(
        "{0} {1}".format(prompt, suffix),
        default_value,
        history_name="confirm",
        completer_words=["y", "n"],
    ).lower()
    if not res:
        return default
    return res == "y"


def wait_for_continue() -> None:
    """等待用户确认后继续回到主菜单。"""
    try:
        prompt_text("按回车键继续", history_name="continue")
    except KeyboardInterrupt:
        print()
