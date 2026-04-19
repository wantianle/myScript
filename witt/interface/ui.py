import subprocess
from io import StringIO
from pathlib import Path
from shutil import which
from typing import List, Optional, Sequence

from rich import box
from rich.align import Align
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from core.models import ChannelInfo, LibraryEntry, ReplayHistoryEntry, TaskEntry

_THEME = Theme(
    {
        "title": "bold cyan",
        "subtitle": "bright_black",
        "accent": "bold green",
        "label": "bold bright_cyan",
        "info": "green",
        "warn": "yellow",
        "error": "bold red",
        "border": "bright_black",
        "header": "bold cyan",
        "muted": "bright_black",
        "ok": "green",
        "bad": "red",
    }
)
_CONSOLE = Console(theme=_THEME, highlight=False)


def print_banner() -> None:
    """打印程序主标题。"""
    banner_text = Text(justify="center")
    banner_text.append("witt\n", style="title")
    banner_text.append("What Is That Tag? v2.0.0", style="subtitle")
    _CONSOLE.print(
        Panel.fit(
            Align.center(banner_text),
            border_style="border",
            padding=(0, 3),
            title="MINIEYE Replay Toolkit",
            title_align="left",
        )
    )


def _build_page_intro_panel(
    title: str,
    summary: str = "",
    hint: str = "",
) -> Panel:
    """构建页面顶部说明面板。"""
    lines = []
    if summary:
        lines.append(Text(summary, style="accent"))
    if hint:
        lines.append(Text(hint, style="muted"))
    body = Group(*lines) if lines else Text("", style="muted")
    return Panel(
        body,
        title=title,
        border_style="border",
        padding=(0, 2),
    )


def _build_info_panel(
    title: str,
    lines: Sequence[Text],
    hint: str = "",
) -> Panel:
    """构建上下文信息面板。"""
    panel_lines = list(lines)
    if hint:
        panel_lines.append(Text(hint, style="muted"))
    return Panel(
        Group(*panel_lines),
        title=title,
        border_style="border",
        padding=(0, 2),
    )


def show_command_help(command_specs, target_command_name: str = "") -> None:
    """打印命令帮助面板。"""
    summary = "命令驱动 REPL 入口与别名一览"
    if target_command_name:
        summary = "查看命令: {0}".format(target_command_name)
    _CONSOLE.print(
        _build_page_intro_panel(
            "命令帮助",
            summary,
            "输入 help <command> 查看单个命令，输入 clear 清屏",
        )
    )
    help_table = Table(
        title="命令详情" if target_command_name else "可用命令",
        box=box.SIMPLE_HEAVY,
        header_style="header",
        expand=True,
    )
    help_table.add_column("命令", style="accent", min_width=12)
    help_table.add_column("别名", style="label", min_width=12)
    help_table.add_column("说明", style="label", min_width=24)
    help_table.add_column("示例", style="muted", min_width=16)
    filtered_specs = []
    for command_spec in command_specs:
        if not target_command_name or command_spec.name == target_command_name:
            filtered_specs.append(command_spec)
    for command_spec in filtered_specs:
        help_table.add_row(
            command_spec.name,
            ", ".join(command_spec.aliases) or "-",
            command_spec.summary,
            command_spec.example,
        )
    if not filtered_specs:
        _CONSOLE.print(
            Panel.fit(
                Text("未找到对应命令帮助", style="warn"),
                title="命令帮助",
                border_style="border",
            )
        )
        return
    _CONSOLE.print(help_table)


def show_environment_summary(session) -> None:
    """打印当前会话环境摘要。"""
    _CONSOLE.print(
        _build_page_intro_panel(
            "当前环境",
            "车号 {0} | 日期 {1}".format(
                session.ctx.vehicle or "未设置",
                session.ctx.target_date or "未设置",
            ),
            "修改 settings.yaml 后执行 config，重建当前会话配置",
        )
    )
    env_table = Table(
        title="会话上下文",
        box=box.SIMPLE_HEAVY,
        header_style="header",
        expand=True,
        show_header=False,
    )
    env_table.add_column("字段", style="label", width=16)
    env_table.add_column("值", style="accent")
    env_table.add_row("车号", session.ctx.vehicle or "未设置")
    env_table.add_row("日期", session.ctx.target_date or "未设置")
    env_table.add_row("模式", str(getattr(session.ctx.logic, "mode", "")) or "未设置")
    env_table.add_row("源路径", str(session.ctx.host.data_root))
    env_table.add_row("扫描/导出路径", str(session.ctx.host.dest_root))
    env_table.add_row("工作目录", str(session.ctx.work_dir))
    env_table.add_row(
        "历史文件",
        str(getattr(getattr(session, "replay_history_repository", None), "history_path", "")),
    )
    env_table.add_row("日志目录", str(session.ctx.log_dir))
    _CONSOLE.print(env_table)


def show_playback_library(
    library: Sequence[LibraryEntry],
    vehicle: str,
    target_date: str,
    search_keyword: str = "",
    total_count: Optional[int] = None,
) -> None:
    """打印回放库列表。"""
    _CONSOLE.print(
        _build_selector_state_panel(
            "回放库",
            "回播条目",
            len(library),
            total_count,
            search_keyword,
        )
    )
    if not library:
        _CONSOLE.print(
            _build_selector_empty_panel(
                "回放库",
                "回播条目",
                search_keyword,
            )
        )
        return
    title = "回放库  {0} | {1}".format(vehicle, target_date)
    if search_keyword:
        title = "{0}  |  过滤: {1}".format(title, search_keyword)
    table = Table(
        title=title,
        box=box.SIMPLE_HEAVY,
        header_style="header",
        expand=True,
    )
    table.add_column("ID", justify="right", style="accent", width=4)
    table.add_column("Tag时间", style="label", min_width=10)
    table.add_column("Tag记录", style="accent", min_width=18)
    table.add_column("soc1 update", style="muted", min_width=16)
    table.add_column("soc2 update", style="muted", min_width=16)
    for index, entry in enumerate(library, 1):
        meta = entry.last_update or {}
        table.add_row(
            str(index),
            entry.time,
            entry.tag,
            meta.get("soc1", "N/A"),
            meta.get("soc2", "N/A"),
        )
    _CONSOLE.print(table)


def show_source_task_entries(
    task_entries: Sequence[TaskEntry],
    search_keyword: str = "",
    total_count: Optional[int] = None,
) -> None:
    """打印原始查询结果列表。"""
    _CONSOLE.print(
        _build_selector_state_panel(
            "查询结果",
            "Tag",
            len(task_entries),
            total_count,
            search_keyword,
        )
    )
    if not task_entries:
        _CONSOLE.print(
            _build_selector_empty_panel(
                "查询结果",
                "Tag",
                search_keyword,
            )
        )
        return
    title = "查询结果"
    if search_keyword:
        title = "查询结果  |  过滤: {0}".format(search_keyword)
    table = Table(
        title=title,
        box=box.SIMPLE_HEAVY,
        header_style="header",
        expand=True,
    )
    table.add_column("ID", justify="right", style="accent", width=4)
    table.add_column("Tag时间", style="label", min_width=16)
    table.add_column("Tag", style="accent", min_width=18)
    table.add_column("soc1", justify="right", style="muted", width=6)
    table.add_column("soc2", justify="right", style="muted", width=6)
    table.add_column("记录数", justify="right", style="label", width=8)
    for index, task_entry in enumerate(task_entries, 1):
        soc1_count = len(task_entry.soc_paths.get("soc1", []))
        soc2_count = len(task_entry.soc_paths.get("soc2", []))
        table.add_row(
            str(index),
            task_entry.time,
            task_entry.name,
            str(soc1_count) if soc1_count else "-",
            str(soc2_count) if soc2_count else "-",
            str(len(task_entry.paths)),
        )
    _CONSOLE.print(table)


def show_channel_candidates(
    channels: Sequence[ChannelInfo],
    search_keyword: str = "",
    total_count: Optional[int] = None,
) -> None:
    """打印频道候选列表。"""
    _CONSOLE.print(
        _build_selector_state_panel(
            "频道列表",
            "频道",
            len(channels),
            total_count,
            search_keyword,
        )
    )
    if not channels:
        _CONSOLE.print(
            _build_selector_empty_panel(
                "频道列表",
                "频道",
                search_keyword,
            )
        )
        return
    title = "频道列表"
    if search_keyword:
        title = "频道列表  |  过滤: {0}".format(search_keyword)
    table = Table(
        title=title,
        box=box.SIMPLE_HEAVY,
        header_style="header",
        expand=True,
    )
    table.add_column("ID", justify="right", style="accent", width=4)
    table.add_column("Channel", style="accent", min_width=24)
    table.add_column("Msg Count", justify="right", style="label", width=10)
    for index, channel in enumerate(channels, 1):
        table.add_row(
            str(index),
            channel.name,
            str(channel.count),
        )
    _CONSOLE.print(table)


def print_text_block(text: str) -> None:
    """按原样打印多行文本块。"""
    if not text:
        return
    _CONSOLE.print(Text.from_ansi(text), end="" if text.endswith("\n") else "\n")


def show_manual_play_header() -> None:
    """打印手动回播模式标题。"""
    _CONSOLE.print(
        _build_page_intro_panel(
            "手动回播模式",
            "将 record 文件/目录粘贴或拖入终端",
            "输入 q 返回，支持直接粘贴路径或拖拽目录",
        )
    )


def show_config_section(
    title: str,
    summary: str = "",
    hint: str = "",
) -> None:
    """打印配置采集阶段的页面头。"""
    _CONSOLE.print(_build_page_intro_panel(title, summary, hint))


def show_flow_section(
    title: str,
    summary: str = "",
    hint: str = "",
) -> None:
    """打印用例流入口页头。"""
    _CONSOLE.print(_build_page_intro_panel(title, summary, hint))


def show_result_section(
    title: str,
    summary: str,
    level: str = "INFO",
    details: Optional[Sequence[str]] = None,
    next_step: str = "",
) -> None:
    """打印统一风格的流程结束态页面。"""
    level_style_map = {
        "INFO": "info",
        "WARN": "warn",
        "ERROR": "error",
    }
    style_name = level_style_map.get(level, "info")
    lines = [Text(summary, style=style_name)]
    for detail_text in details or []:
        lines.append(Text(detail_text, style="muted"))
    if next_step:
        lines.append(
            Text.assemble(
                ("下一步: ", "label"),
                (next_step, "accent"),
            )
        )
    _CONSOLE.print(
        Panel(
            Group(*lines),
            title=title,
            border_style=style_name,
            padding=(0, 2),
        )
    )


def show_replay_section(
    title: str,
    summary: str = "",
    hint: str = "",
) -> None:
    """打印回播参数采集阶段的页面头。"""
    _CONSOLE.print(_build_page_intro_panel(title, summary, hint))


def show_option_choices(
    title: str,
    prompt: str,
    options: Sequence[str],
    default_index: int = 0,
    summary: str = "",
) -> None:
    """打印统一风格的选项列表。"""
    hint = "输入序号或选项名"
    if default_index and 1 <= default_index <= len(options):
        hint = "{0}，回车使用默认项".format(hint)
    _CONSOLE.print(
        _build_page_intro_panel(
            title,
            summary or prompt,
            hint,
        )
    )
    table = Table(
        title="候选项",
        box=box.SIMPLE_HEAVY,
        header_style="header",
        expand=True,
    )
    table.add_column("ID", justify="right", style="accent", width=4)
    table.add_column("选项", style="accent", min_width=16)
    table.add_column("默认", style="muted", width=8)
    for option_index, option_text in enumerate(options, 1):
        default_marker = "是" if option_index == default_index else ""
        table.add_row(
            str(option_index),
            option_text,
            default_marker,
        )
    _CONSOLE.print(table)


def show_playback_info(
    tag: str,
    duration: int,
    rate: float = 1.0,
    channels: Optional[List[str]] = None,
    command: str = "",
) -> None:
    """打印当前回放的概要信息。"""
    lines = [
        Text.assemble(("当前回播: ", "label"), (tag, "accent")),
        Text.assemble(("总时长: ", "label"), ("{0}s".format(duration), "accent")),
        Text.assemble(("播放倍速: ", "label"), ("x{0:g}".format(rate), "accent")),
    ]
    if channels:
        lines.append(
            Text.assemble(
                ("频道过滤: ", "label"),
                (", ".join(channels), "accent"),
            )
        )
    if command:
        lines.append(
            Text.assemble(
                ("执行指令: ", "label"),
                (command, "accent"),
            )
        )
    _CONSOLE.print(_build_info_panel("回播信息", lines, "Ctrl+C 中断当前回播"))


def show_replay_history(history_entries: List[ReplayHistoryEntry]) -> None:
    """打印回播历史列表。"""
    _CONSOLE.print(
        _build_selector_state_panel(
            "回播历史",
            "历史记录",
            len(history_entries),
            len(history_entries),
            "",
        )
    )
    if not history_entries:
        _CONSOLE.print(_build_selector_empty_panel("回播历史", "历史记录"))
        return
    _CONSOLE.print(_build_history_table(history_entries))


def show_filtered_replay_history(
    history_entries: List[ReplayHistoryEntry],
    search_keyword: str = "",
    total_count: Optional[int] = None,
) -> None:
    """打印带筛选状态的回播历史列表。"""
    _CONSOLE.print(
        _build_selector_state_panel(
            "回播历史",
            "历史记录",
            len(history_entries),
            total_count,
            search_keyword,
        )
    )
    if not history_entries:
        _CONSOLE.print(
            _build_selector_empty_panel(
                "回播历史",
                "历史记录",
                search_keyword,
            )
        )
        return
    _CONSOLE.print(_build_history_table(history_entries))


def browse_replay_history(history_entries: List[ReplayHistoryEntry]) -> None:
    """使用 less 浏览回播历史；不可用时退化为直接打印。"""
    history_text = render_replay_history(history_entries)
    if which("less") is None:
        _CONSOLE.print(Text.from_ansi(history_text), end="")
        return
    subprocess.run(
        ["less", "-R", "+G"],
        input=history_text,
        text=True,
        check=False,
    )


def render_replay_history(history_entries: List[ReplayHistoryEntry]) -> str:
    """渲染回播历史文本，便于直接打印或交给 less。"""
    buffer = StringIO()
    history_console = Console(
        file=buffer,
        theme=_THEME,
        highlight=False,
        force_terminal=True,
        color_system="standard",
        width=140,
    )
    history_console.print(_build_history_table(history_entries))
    return buffer.getvalue()


def _build_history_table(history_entries: List[ReplayHistoryEntry]) -> Table:
    """构建回播历史表格。"""
    table = Table(
        title="回播历史",
        box=box.SIMPLE_HEAVY,
        header_style="header",
        expand=True,
    )
    table.add_column("序号", justify="right", style="accent", width=4)
    table.add_column("创建时间", style="label", min_width=16)
    table.add_column("Tag时间", style="label", min_width=16)
    table.add_column("车号", style="accent", min_width=10)
    table.add_column("模式", style="muted", min_width=16)
    table.add_column("Tag", style="accent", min_width=18)
    table.add_column("range", style="label", min_width=10)
    table.add_column("rate", style="label", min_width=8)
    table.add_column("-k", style="muted", min_width=10)
    table.add_column("状态", style="label", min_width=8)
    for index, history_entry in enumerate(history_entries, 1):
        source_mode_text = "{0}/{1}".format(
            history_entry.source_type,
            history_entry.replay_mode,
        )
        table.add_row(
            str(index),
            history_entry.created_at or "未知时间",
            history_entry.issue_timestamp or "未知时间",
            history_entry.vehicle or "未知车型",
            source_mode_text,
            history_entry.display_tag or history_entry.selection_label or "未命名回播",
            _format_history_range(history_entry.start_sec, history_entry.end_sec),
            "x{0:g}".format(history_entry.playback_rate),
            _format_history_channels(history_entry.channel_filters),
            _format_history_status(history_entry),
        )
    return table


def _build_selector_state_panel(
    page_title: str,
    item_label: str,
    visible_count: int,
    total_count: Optional[int] = None,
    search_keyword: str = "",
) -> Panel:
    """构建选择页顶部状态块。"""
    actual_total_count = visible_count if total_count is None else total_count
    filter_text = "/{0}".format(search_keyword) if search_keyword else "无"
    filter_style = "accent" if search_keyword else "muted"
    lines = [
        Text.assemble(("当前筛选: ", "label"), (filter_text, filter_style)),
        Text.assemble(
            ("可见{0}: ".format(item_label), "label"),
            ("{0}/{1}".format(visible_count, actual_total_count), "accent"),
        ),
        Text("输入 /关键字 筛选，输入 / 清空筛选，回车返回", style="muted"),
    ]
    if search_keyword and visible_count == 0:
        lines.append(Text("当前筛选没有匹配结果，可继续输入新关键字或输入 / 清空筛选", style="warn"))
    return Panel(
        Group(*lines),
        title="{0}状态".format(page_title),
        border_style="border",
        padding=(0, 2),
    )


def _build_selector_empty_panel(
    page_title: str,
    item_label: str,
    search_keyword: str = "",
) -> Panel:
    """构建选择页空状态面板。"""
    if search_keyword:
        body = Group(
            Text("没有匹配到{0}".format(item_label), style="warn"),
            Text("当前筛选: /{0}".format(search_keyword), style="muted"),
            Text("输入新的 /关键字，或输入 / 清空筛选", style="muted"),
        )
    else:
        body = Group(
            Text("当前没有可用的{0}".format(item_label), style="warn"),
            Text("请调整查询条件后重试", style="muted"),
        )
    return Panel(
        body,
        title="{0}空状态".format(page_title),
        border_style="border",
        padding=(0, 2),
    )


def _format_history_range(start_sec: int, end_sec: int) -> str:
    """格式化历史记录中的回播时间范围。"""
    if start_sec <= 0 and end_sec <= 0:
        return "全播"
    if end_sec > 0:
        return "{0}-{1}s".format(start_sec, end_sec)
    return "{0}s-全播".format(start_sec)


def _format_history_channels(channel_filters: List[str]) -> str:
    """压缩展示频道过滤信息。"""
    if not channel_filters:
        return "无"
    if len(channel_filters) <= 2:
        return ", ".join(channel_filters)
    return "{0}, {1} ...(+{2})".format(
        channel_filters[0],
        channel_filters[1],
        len(channel_filters) - 2,
    )


def _format_history_status(history_entry: ReplayHistoryEntry) -> Text:
    """展示历史记录当前是否可直接回播。"""
    if not history_entry.records:
        return Text("空记录", style="warn")
    missing_paths = [
        replay_record.path
        for replay_record in history_entry.records
        if not Path(replay_record.path).exists()
    ]
    if missing_paths:
        return Text("路径失效", style="error")
    return Text("可回播", style="ok")


def print_status(msg: str, level: str = "INFO") -> None:
    """打印终端即时状态，不进入日志文件。"""
    level_style_map = {
        "INFO": "info",
        "WARN": "warn",
        "ERROR": "error",
    }
    style_name = level_style_map.get(level, "info")
    _CONSOLE.print(
        Text.assemble(
            ("[{0}] ".format(level), style_name),
            (msg, style_name),
        )
    )
