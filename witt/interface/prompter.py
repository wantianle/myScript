import os
import re
import urllib.parse
import questionary
from questionary import Choice
from pathlib import Path
from typing import List

from core.errors import RecordInfoError
from core.session import AppSession
from interface import ui
from utils import parser

MAIN_MENU_CHOICES = [
    Choice(title="[全流程] 查询 -> 切片 -> 回放", value="1"),
    Choice(title="[仅回播] 手动选择/自动扫描回播", value="2"),
    Choice(title="[仅同步] 同步本地 mdrive 版本", value="3"),
    Choice(title="[进容器] 交互式进 docker bash", value="4"),
    Choice(title="[回灌红绿灯] 一键回灌红绿灯数据", value="5"),
    Choice(title="[ 退出 ]", value="q"),
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


def get_user_input(prompt: str, default_value: str):
    try:
        val = input(f"\033[32m{prompt}\033[0m (默认 {default_value}): ").strip()
        return val if val else default_value
    except KeyboardInterrupt:
        print()
        raise


def get_int_input(prompt: str, default_value) -> int:
    while True:
        raw_val = get_user_input(prompt, str(default_value))
        try:
            return int(raw_val)
        except ValueError:
            ui.print_status("请输入整数", "WARN")


def choose_option(prompt: str, options: List[str], index: bool = False):
    for i, opt in enumerate(options, 1):
        print(f"[{i}] {opt}  ", end="")
    while True:
        val = input(f"\033[32m{prompt}: \033[0m").strip()
        if val.isdigit() and 1 <= int(val) <= len(options):
            return int(val) if index else options[int(val) - 1]
        ui.print_status("输入无效，请重新选择", "WARN")


def get_basic_params(config: dict):
    ui.print_status("基本信息配置")
    config["logic"]["target_date"] = get_user_input(
        "数据日期", config["logic"]["target_date"]
    )
    config["logic"]["vehicle"] = get_vehicle_name()


def get_vehicle_name():
    prefix = choose_option("\n选择车辆类型", ["XZB6", "XZT5"])
    while True:
        num = input("\033[32m输入车辆号: \033[0m").strip()
        if not num:
            num = "00000"
        if num.isdigit() and 0 <= int(num) <= 99999:
            num = num.zfill(5)
            break
        ui.print_status("编号必须是 0-99999", "ERROR")
    vehicle = f"{prefix}{num}"
    print(f"\033[1;33m@{vehicle}\033[0m")
    return vehicle


def get_split_params(config: dict):
    while True:
        before = get_int_input("切片 tag 前多少秒", config["logic"]["before"])
        after = get_int_input("切片 tag 后多少秒", config["logic"]["after"])
        if before < 0:
            ui.print_status("before 不能小于 0", "WARN")
            continue
        if before + after <= 0:
            ui.print_status("切片总时长必须大于 0 秒", "WARN")
            continue
        config["logic"]["before"] = before
        config["logic"]["after"] = after
        return


def get_path_params(config: dict):
    # soc_inx = get_user_input("选择 [1] soc1 [2] soc2", "all")
    # if soc_inx == "all":
    #     soc_inx = ""
    # config["logic"]["soc"] = f"soc{soc_inx}"
    config["logic"]["mode"] = int(choose_option("\n数据输入模式", ["本地", "NAS", "车端"], True))
    if config["logic"]["mode"] == 1:
        config["host"]["data_root"] = get_user_input(
            "原始数据路径 (限/media下)", config["host"]["data_root"]
        )
    config["host"]["dest_root"] = get_user_input(
        "切片导出路径 (限/media下)", config["host"]["dest_root"]
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
        raw_input = input(f"{prompt}\n单选 1,3,5 | 多选 2-6 | 反选 0 5 7-15 | 全选 0: ").strip()
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


def select_main_menu_action():
    return questionary.select(
        "请选择操作 :",
        choices=MAIN_MENU_CHOICES,
        use_shortcuts=True,
        style=MAIN_MENU_STYLE,
    ).ask()


def wait_for_continue():
    try:
        input("按回车键继续...")
    except KeyboardInterrupt:
        print()


def get_json_input() -> str:
    """获取 version.json 输入：支持路径拖拽和内容粘贴"""
    while True:
        try:
            raw_data = input("拖拽或粘贴输入 version 文件路径:").strip()
            if not raw_data:
                ui.print_status("输入为空，请重新输入！", "WARN")
                continue
            proc_path = raw_data.strip("'\"").replace("file://", "")
            proc_path = urllib.parse.unquote(proc_path)
            if os.path.exists(proc_path):
                return proc_path
        except KeyboardInterrupt:
            ui.print_status("已取消...")
            return ""


def update_dest_root(config: dict, prompt: str) -> None:
    config["host"]["dest_root"] = get_user_input(
        prompt,
        config["host"]["dest_root"],
    )


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
    try:
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
                socs.add(soc)
    except RecordInfoError as e:
        ui.print_status(str(e), "ERROR")
        raise
    except Exception as e:
        ui.print_status("频道获取失败", "ERROR")
        raise e
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
