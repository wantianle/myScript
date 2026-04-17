import os
import urllib.parse

from . import prompter
from . import ui


def get_vehicle_name(default_vehicle: str = "") -> str:
    """交互式采集并格式化车辆编号。"""
    default_prefix = default_vehicle[:4] if len(default_vehicle) >= 4 else ""
    default_vehicle_number = default_vehicle[-5:] if len(default_vehicle) >= 5 else "00000"
    default_index = 1 if default_prefix == "XZB6" else 2 if default_prefix == "XZT5" else 0
    vehicle_prefix = prompter.choose_option(
        "\n选择车辆类型",
        ["XZB6", "XZT5"],
        default_index=default_index,
    )
    while True:
        vehicle_number = input(
            "\033[32m输入车辆号 (默认 {0}): \033[0m".format(default_vehicle_number)
        ).strip()
        if not vehicle_number:
            vehicle_number = default_vehicle_number
        if vehicle_number.isdigit() and 0 <= int(vehicle_number) <= 99999:
            vehicle_number = vehicle_number.zfill(5)
            break
        ui.print_status("编号必须是 0-99999", "ERROR")
    vehicle_name = f"{vehicle_prefix}{vehicle_number}"
    print(f"\033[1;33m@{vehicle_name}\033[0m")
    return vehicle_name


def get_basic_params(ctx) -> None:
    """采集基础业务参数，包括日期和车辆。"""
    ui.print_status("基本信息配置")
    ctx.logic.target_date = prompter.get_user_input(
        "数据日期",
        ctx.logic.target_date,
    )
    ctx.logic.vehicle = get_vehicle_name(ctx.logic.vehicle)


def get_split_params(ctx) -> None:
    """采集切片时间窗参数并完成基础校验。"""
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


def get_source_path_params(ctx, allow_remote: bool = True) -> None:
    """采集数据源路径参数。"""
    options = ["本地", "NAS"]
    if allow_remote:
        options.append("车端")
    ctx.logic.mode = int(
        prompter.choose_option("\n数据输入模式", options, True)
    )
    if ctx.logic.mode == 1:
        ctx.host.data_root = prompter.get_user_input(
            "原始数据路径 (限/media下)",
            ctx.host.data_root,
        )


def get_export_path_params(ctx) -> None:
    """采集切片导出路径。"""
    ctx.host.dest_root = prompter.get_user_input(
        "切片导出路径 (限/media下)",
        ctx.host.dest_root,
    )


def get_path_params(ctx) -> None:
    """采集数据源路径和导出路径等与路径相关的配置。"""
    get_source_path_params(ctx)
    get_export_path_params(ctx)
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
    """更新导出根目录。"""
    ctx.host.dest_root = prompter.get_user_input(
        prompt,
        ctx.host.dest_root,
    )
