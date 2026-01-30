import json
import os
import re
import sys
import subprocess
import select
import urllib.parse
import questionary
from questionary import Choice
from pathlib import Path
from typing import List

from core.session import AppSession
from interface import ui
from utils import parser


def usage():
    README = Path(__file__).resolve().parents[1] / "docs" / "README.md"
    subprocess.run(["python3", "-m", "rich.markdown", README])


def get_user_input(prompt: str, default_value: str) -> str:
    try:
        val = input(f"\033[32m{prompt}\033[0m (默认 {default_value}): ").strip()
        return val if val else default_value
    except KeyboardInterrupt:
        print()
        raise


def get_basic_params(config: dict):
    ui.print_status("基本信息配置")
    config["logic"]["target_date"] = get_user_input(
        "日期", config["logic"]["target_date"]
    )
    config["logic"]["vehicle"] = get_user_input("车辆名", config["logic"]["vehicle"])


def get_split_params(config: dict):
    config["logic"]["before"] = int(
        get_user_input("tag 前多少秒", config["logic"]["before"])
    )
    config["logic"]["after"] = int(
        get_user_input(
            "tag 后多少秒",
            config["logic"]["after"],
        )
    )


def get_path_params(config: dict):
    soc_inx = get_user_input("选择 [1] soc1 [2] soc2", "all")
    if soc_inx == "all":
        soc_inx = ""
    config["logic"]["soc"] = f"soc{soc_inx}"
    config["host"]["dest_root"] = get_user_input(
        "导出路径 (/media下)", config["host"]["dest_root"]
    )
    config["host"]["data_root"] = get_user_input(
        "数据根路径(/media下)", config["host"]["data_root"]
    )
    get_split_params(config)
    # bash 调试
    # config["env"]["debug"] = get_user_input("bash 调试模式", config["env"]["debug"])


def get_selected_indices(all_tasks: list, prompt="请输入要处理的序号") -> list:
    """
    通用序号获取方法 带预览与重试逻辑
    :param all_tasks: 原始任务列表，用于获取长度和预览内容
    :param prompt: 输入提示词
    :return: 选中的任务对象列表
    """
    total_count = len(all_tasks)
    if total_count == 0:
        ui.print_status("任务列表为空", "ERROR")
        return []

    while True:
        raw_input = input(f"{prompt}\neg. 1,3; 2-6; 0(全选); 0 5 7-15(排除): ").strip()
        # 预清洗：只保留数字、横杠、逗号、空白、换行
        clean_input = re.sub(r"[^\d\-,\s\n]", "", raw_input)
        # 分词
        tokens = [t for t in re.split(r"[,\s\n]+", clean_input) if t]
        if not tokens:
            ui.print_status("输入为空，请重新输入", "WARN")
            continue

        full_set = set(range(1, total_count + 1))
        result_set = set()

        # 核心解析
        is_exclude_mode = tokens[0] == "0"
        if is_exclude_mode:
            result_set = full_set.copy()
            tokens = tokens[1:]
        for token in tokens:
            try:
                if "-" in token and not token.startswith("-"):
                    # 处理范围 (如 10-12)
                    parts = token.split("-")
                    start, end = int(parts[0]), int(parts[1])
                    scope = set(range(min(start, end), max(start, end) + 1))
                    if is_exclude_mode:
                        result_set -= scope
                    else:
                        result_set |= scope
                else:
                    # 处理单点 (如 5 或 -20)
                    val = abs(int(token))
                    if is_exclude_mode:
                        result_set.discard(val)
                    else:
                        result_set.add(val)
            except (ValueError, IndexError):
                ui.print_status("输入无效，请重新输入", "WARN")
                continue
        # 过滤越界序号并排序
        final_ids = sorted([i for i in result_set if 1 <= i <= total_count])
        if not final_ids:
            ui.print_status("未选中任何有效序号，请检查输入", "ERROR")
            continue

        # 预览
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


def get_json_input() -> str:
    """获取 version.json 输入：支持路径拖拽和内容粘贴"""
    while True:
        ui.print_status(
            "直接拖拽 or 输入 version.json 内容或文件路径 (回车 + Ctrl D 结束):"
        )
        try:
            raw_data = sys.stdin.read().strip()
            if not raw_data:
                ui.print_status("输入内容为空，请重新输入！", "WARN")
                continue
            proc_path = raw_data.strip("'\"").replace("file://", "")
            proc_path = urllib.parse.unquote(proc_path)
            if os.path.exists(proc_path):
                return proc_path
            try:
                json_obj = json.loads(raw_data)
                return json.dumps(json_obj)
            except json.JSONDecodeError:
                ui.print_status("非法 JSON 格式！", "WARN")
                continue
        except KeyboardInterrupt:
            ui.print_status("已取消...")
            return ""


def get_dragged_input() -> list:
    """
    解决拖拽多文件自带换行的问题。
    嗅探标准输入缓冲区，把所有排队中的路径一次性读完。
    处理拖拽进终端的字符串：
    1. 自动去引号
    2. 兼容空格分隔的多文件；兼容 Kitty/Gnome 终端常见的路径格式
    3. 还原空格、中文字符、特殊符号编码
    4. 过滤出 .record 文件或目录
    5. 去重并进行排序：根据 record 序列号 (.00001) 排序
    """
    ui.print_status("请拖入任意文件/目录:")
    lines = [sys.stdin.readline()]
    while select.select([sys.stdin], [], [], 0.1)[0]:
        line = sys.stdin.readline()
        if line:
            lines.append(line)
        else:
            break
    raw_input = "".join(lines).strip()
    if raw_input.lower() == "q":
        return []
    if not raw_input:
        return []
    normalized = raw_input.replace("\r", " ").replace("\n", " ")
    if "file://" in normalized:
        parts = [p.strip() for p in normalized.split("file://") if p.strip()]
        paths = [urllib.parse.unquote(p) for p in parts]
    else:
        # 保留引号内路径的同时，正确分割一长串路径
        paths = re.findall(r'(?:[^\s"\']|["\'][^"\']*["\'])+', normalized)
        paths = [p.strip("'\"") for p in paths]

    record_files = []
    for p in paths:
        path_obj = Path(p)
        if not path_obj.exists():
            continue
        if path_obj.is_dir():
            for f in path_obj.rglob("*"):
                if f.is_file() and ".record" in f.name:
                    record_files.append(f)
        else:
            if ".record" in path_obj.name:
                record_files.append(path_obj)
    paths = parser.sort_records(list(set(record_files)))
    if not paths:
        ui.print_status("无效路径", "ERROR")
    print("没有返回？")
    return paths


def select_channels_wizard(channels: List[dict], prompt: str) -> List[str]:
    """勾选式频道选择器"""
    choices = [
        Choice(
            title=f"{ch['name']:<20} (Msg Count: {ch.get('count', 0)})",
            value=ch["name"],
        )
        for ch in channels
    ]
    selected = questionary.checkbox(
        prompt,
        choices=choices,
        style=questionary.Style(
            [
                ("pointer", "fg:cyan bold"),
                ("highlighted", "fg:cyan bold"),
                ("selected", "fg:red"),
            ]
        ),
    ).ask()
    return selected if selected is not None else []


def get_channels(session: "AppSession", tasks: List[dict]) -> List[dict]:
    """从多个 record 中提取频道并集，支持双 SOC 路径检查"""
    channels_map = {}
    socs = set()
    for t in tasks:
        path_list = t.get("paths", [])
        for p in path_list:
            soc = Path(p).parent.name[-4:]
            if soc in socs:
                continue
            info = session.recorder.get_info(p)
            channels = info.get("channels", [])
            for ch in channels:
                name = ch["name"]
                if name not in channels_map:
                    channels_map[name] = ch.copy()
                    channels_map[name].setdefault("count", 0)
                else:
                    channels_map[name]["count"] += ch.get("count", 0)
            socs.update(soc)
    return sorted(channels_map.values(), key=lambda x: x["name"])


def get_tasks_channels(session: AppSession, tasks: List[dict]) -> List[str]:
    """过滤要播放的频道"""
    if not get_confirm_input("是否过滤 Channel?"):
        return []
    try:
        unique_channels = get_channels(session, tasks)
    except Exception as e:
        ui.print_status("频道获取失败", "ERROR")
        raise e
    return select_channels_wizard(unique_channels, prompt="请【选中】要删除的频道:")
