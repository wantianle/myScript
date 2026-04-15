import os
import urllib.parse

from . import prompter
from . import ui


def get_vehicle_name():
    vehicle_prefix = prompter.choose_option("\n选择车辆类型", ["XZB6", "XZT5"])
    while True:
        vehicle_number = input("\033[32m输入车辆号: \033[0m").strip()
        if not vehicle_number:
            vehicle_number = "00000"
        if vehicle_number.isdigit() and 0 <= int(vehicle_number) <= 99999:
            vehicle_number = vehicle_number.zfill(5)
            break
        ui.print_status("编号必须是 0-99999", "ERROR")
    vehicle_name = f"{vehicle_prefix}{vehicle_number}"
    print(f"\033[1;33m@{vehicle_name}\033[0m")
    return vehicle_name


def get_basic_params(ctx):
    ui.print_status("基本信息配置")
    ctx.logic.target_date = prompter.get_user_input(
        "数据日期",
        ctx.logic.target_date,
    )
    ctx.logic.vehicle = get_vehicle_name()


def get_split_params(ctx):
    while True:
        before = prompter.get_int_input("切片 tag 前多少秒", ctx.logic.before)
        after = prompter.get_int_input("切片 tag 后多少秒", ctx.logic.after)
        if before < 0:
            ui.print_status("before 不能小于 0", "WARN")
            continue
        if before + after <= 0:
            ui.print_status("切片总时长必须大于 0 秒", "WARN")
            continue
        ctx.logic.before = before
        ctx.logic.after = after
        return


def get_path_params(ctx):
    ctx.logic.mode = int(
        prompter.choose_option("\n数据输入模式", ["本地", "NAS", "车端"], True)
    )
    if ctx.logic.mode == 1:
        ctx.host.data_root = prompter.get_user_input(
            "原始数据路径 (限/media下)",
            ctx.host.data_root,
        )
    ctx.host.dest_root = prompter.get_user_input(
        "切片导出路径 (限/media下)",
        ctx.host.dest_root,
    )
    get_split_params(ctx)


def get_json_input() -> str:
    """获取 version.json 输入：支持路径拖拽和内容粘贴"""
    while True:
        try:
            raw_data = input("拖拽或粘贴输入 version 文件路径:").strip()
            if not raw_data:
                ui.print_status("输入为空，请重新输入！", "WARN")
                continue
            processed_path = raw_data.strip("'\"").replace("file://", "")
            processed_path = urllib.parse.unquote(processed_path)
            if os.path.exists(processed_path):
                return processed_path
        except KeyboardInterrupt:
            ui.print_status("已取消...")
            return ""


def update_dest_root(ctx, prompt: str) -> None:
    ctx.host.dest_root = prompter.get_user_input(
        prompt,
        ctx.host.dest_root,
    )
