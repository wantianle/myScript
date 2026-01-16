import json
import logging
import os
import re
import sys
import subprocess
from typing import List
import ui
from pathlib import Path
import urllib.parse
import shlex
from utils import handles
from core.engine.recorder import Recorder


def usage() -> None:
    README = Path(__file__).resolve().parents[0] / "docs" / "README"
    subprocess.run(["less", README])


def get_user_input(prompt: str, default_value: str) -> str:
    val = input(f"{prompt} (默认 {default_value}): ").strip()
    return val if val else default_value


def get_json_input() -> str:
    """
    获取 version.json 输入：支持路径拖拽和内容粘贴
    """
    while True:
        print("\n直接拖拽 or 输入 version.json 内容或文件路径 (回车 + Ctrl D 结束):")
        try:
            # 读取输入并做初步清洗
            raw_data = sys.stdin.read().strip()

            if not raw_data:
                ui.print_status("输入内容为空，请重新输入！", "WARN")
                continue

            # 路径处理逻辑 (支持 Kitty/file://)
            processed_path = raw_data.strip("'\"").replace("file://", "")
            processed_path = urllib.parse.unquote(processed_path)

            if os.path.exists(processed_path):
                # 记录审计日志：用户通过路径提供了配置
                logging.info(f"[ENV_SYNC] JSON source is a path: {processed_path}")
                return processed_path

            # 作为纯 JSON 内容处理
            try:
                json_obj = json.loads(raw_data)
                # 记录日志：用户通过粘贴内容提供了配置
                logging.info("[ENV_SYNC] JSON source is raw text content")
                return json.dumps(json_obj)
            except json.JSONDecodeError as e:
                ui.print_status(
                    "输入既不是有效路径，也不是合法的 JSON 格式，请检查！", "ERR"
                )
                # 记录日志 DEBUG
                logging.debug(
                    f"[JSON_PARSE_ERR] Content: {raw_data[:100]}... | Error: {e}"
                )
                continue

        except KeyboardInterrupt:
            # Ctrl+C 退出输入状态
            print("\n已取消输入")
            return ""
        except Exception as e:
            ui.print_status(f"读取输入发生意外错误: {e}", "ERR")
            # 记录异常堆栈到日志文件
            logging.exception("get_json_input critical error")
            raise e


def get_basic_params(config: dict) -> None:
    print(f"\n{' 基本信息确认 ':-^30}")
    config["logic"]["target_date"] = get_user_input(
        "日期", config["logic"]["target_date"]
    )
    config["logic"]["vehicle"] = get_user_input(
        "车辆名", config["logic"]["vehicle"]
    )


def get_split_params(config: dict) -> None:
    config["logic"]["before"] = int(
        get_user_input(
            "tag 前多少秒", config["logic"]["before"]
        )
    )
    config["logic"]["after"] = int(
        get_user_input(
            "tag 后多少秒",
            config["logic"]["after"],
        )
    )


def get_path_params(config: dict) -> None:
    inx = input("选择 [1] soc1 [2] soc2 (默认 1): ").strip()
    config["logic"]["soc"] = (inx in ("1", "2") and f"soc{inx}") or config["logic"]["soc"]
    config["host"]["dest_root"] = get_user_input(
        "导出路径 (/media下)", config["host"]["dest_root"]
    )
    config["logic"]["mode"] = int(get_user_input(
        "模式 [1] 本地 [2] NAS [3] SSH: ", config["logic"]["mode"]
    ))
    if config["logic"]["mode"] == 1:
        config["host"]["local_path"] = get_user_input(
            "数据根路径(/media下)", config["host"]["local_path"]
        )
    get_split_params(config)
    # config["env"]["debug"] = (
    #     input("bash 调试模式 [y/N] (回车跳过): ").strip().lower() == "y"
    # )


def get_selected_indices(all_tasks: list, prompt="请输入要处理的序号") -> list:
    """
    通用序号获取方法 带预览与重试逻辑
    :param all_tasks: 原始任务列表，用于获取长度和预览内容
    :param prompt: 输入提示词
    :return: 选中的任务对象列表
    """
    total_count = len(all_tasks)
    if total_count == 0:
        ui.print_status("任务列表为空", "ERR")
        return []

    while True:
        raw_input = input(
            f"{prompt}\n( 1,3 |  2-6 | 全选: 0 | 排除: 0 5 7-15): "
        ).strip()
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
            ui.print_status("未选中任何有效序号，请检查输入", "ERR")
            continue

        # 预览
        preview_limit = 10
        display_ids = final_ids[:preview_limit]
        preview_str = ", ".join(map(str, display_ids))
        if len(final_ids) > preview_limit:
            preview_str += f" ..."
        ui.print_status(f"选中待处理序号: [{preview_str}(共 {len(final_ids)} 项)]", "INFO")
        if confirm_action("确认执行？"):
            ui.print_status("已取消...", "WARN")


def select_channels_interactive(recorder: Recorder, record_path: Path):
    """
    展示 Channel 列表并让用户选
    """
    info = recorder.get_info(str(record_path))
    channels = info.get("channels", [])
    ui.show_channel_table(channels)
    selected_indices = get_selected_indices(
        channels, prompt="请选择要【删除】的 Channel 序号"
    )
    return [c["name"] for c in selected_indices]


def confirm_action(prompt: str, default: bool = False) -> bool:
    """通用的二次确认函数"""
    suffix = "[Y/n]" if default else "[y/N]"
    res = (
        input(f"{prompt} {suffix} (回车 {'Y' if default else 'N'}): ")
        .strip()
        .lower()
    )
    if not res:
        return default
    return res == "y"


def sort_record_files(file_list: list) -> list:
    """
    根据 Cyber Record 的序号进行全局排序
    排序规则：先按序号排，序号相同按文件名排（处理 soc1/soc2 同序号情况）
    文件名示例: 20260110125227.record.00005.125739
    """

    def get_index(path):
        match = re.search(r"\.record\.(\d+)", path.name)
        return int(match.group(1)) if match else 0
    return sorted(file_list, key=lambda x: (get_index(x), x.name))


def parse_dragged_paths(raw_str: str) -> list:
    """
    处理拖拽进终端的字符串：
    1. 自动去引号
    2. 兼容空格分隔的多文件；兼容 Kitty/Gnome 终端常见的路径格式
    3. 还原空格、中文字符、特殊符号编码
    4. 过滤出 .record 文件或目录
    5. 去重并进行排序：根据 record 序列号 (.00001) 排序
    """
    clean_str = raw_str.strip()
    parts = []
    if "file://" in clean_str:
        parts = [
            urllib.parse.unquote(p.strip())
            for p in clean_str.split("file://")
            if p.strip()
        ]
    else:
        parts = shlex.split(clean_str)
    all_files = []
    for p in parts:
        path_obj = Path(p)
        if not path_obj.exists():
            continue
        if path_obj.is_dir():
            all_files.extend(list(path_obj.rglob("*.record*")))
        elif ".record" in path_obj.name:
            all_files.append(path_obj)
    return sort_record_files(list(set(all_files)))


def select_playback_channels(session, records) -> List[str]:
    """
    获取多个 SOC 的频道并集，并让用户勾选
    """
    if not confirm_action("是否过滤 Channel 播放?", default=False):
        return []

    # 每个 SOC 取一个文件 info
    soc_sample_files = {}
    for r in records:
        soc_name = Path(r["path"]).parent.name
        if soc_name not in soc_sample_files:
            soc_sample_files[soc_name] = r["path"]

    # 获取所有频道并集
    all_channels_map = {}
    for soc, f_path in soc_sample_files.items():
        logging.info(f"正在读取 {soc} 的频道信息...")
        info = session.recorder.get_info(f_path)
        for ch in info.get("channels", []):
            name = ch["name"]
            if name not in all_channels_map:
                all_channels_map[name] = ch
            else:
                # 累加消息数，仅作展示参考
                all_channels_map[name]["count"] += ch["count"]
    unique_channels = sorted(all_channels_map.values(), key=lambda x: x["name"])
    ui.show_channel_table(unique_channels)
    selected = get_selected_indices(
        unique_channels, prompt="请选择要【保留】的频道序号"
    )
    if not selected:
        return []
    return [c["name"] for c in selected]


def get_cached_playback(session, selected_tag):
    """处理缓存库的回放逻辑"""
    socs = sorted(list(selected_tag["socs"].keys()))
    for i, s in enumerate(socs, 1):
        print(f"  [{i}] {s}")
    if len(socs) > 1:
        print(f"  [{len(socs) + 1}] All")

    choice = input(f"选择 SOC (默认 1): ").strip() or "1"
    target_records = []
    if choice.isdigit() and int(choice) <= len(socs):
        target_records = selected_tag["socs"][socs[int(choice) - 1]]
    else:
        for s in socs:
            target_records.extend(selected_tag["socs"][s])

    selected_channels = select_playback_channels(session, target_records)

    range_in = input("播放范围 (5 | 10-20 | 回车全播): ").strip()
    start_s, end_s = handles.parse_range_logic(range_in)

    session.task_play(target_records, start_s, end_s, selected_channels)
