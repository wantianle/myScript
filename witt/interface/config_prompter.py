import os
import re
import urllib.parse
from typing import Optional

from . import prompter
from . import ui

VEHICLE_PREFIX_HINTS = ["XZB6", "XZT5", "XZA0"]


def get_vehicle_name(default_vehicle: str = "") -> str:
    """交互式采集车辆编号。"""
    while True:
        vehicle_name = prompter.prompt_text(
            "车辆号",
            default_vehicle,
            history_name="vehicle_name",
            completer_words=VEHICLE_PREFIX_HINTS,
        ).upper()
        if _is_valid_vehicle_name(vehicle_name):
            return vehicle_name
        ui.show_input_feedback(
            "车号格式必须是 XZB6/XZT5/XZA0 开头并跟 5 位数字，例如 XZB600001",
            "ERROR",
        )


def _is_valid_vehicle_name(vehicle_name: str) -> bool:
    """校验车辆编号格式。"""
    return bool(re.fullmatch(r"(XZB6|XZT5|XZA0)\d{5}", vehicle_name))


def get_basic_params(ctx) -> None:
    """采集基础业务参数，包括日期和车辆。"""
    ui.show_config_section(
        "基本信息配置",
        "当前车号 {0} | 当前日期 {1}".format(
            ctx.logic.vehicle or "未设置",
            ctx.logic.target_date or "未设置",
        ),
        "先确认日期和车辆，后续查询、扫描和回播都基于这组信息",
    )
    ctx.logic.target_date = prompter.get_user_input(
        "数据日期",
        ctx.logic.target_date,
        history_name="target_date",
    )
    ctx.logic.vehicle = get_vehicle_name(ctx.logic.vehicle)


def get_split_params(ctx, window_name: str = "切片窗口") -> None:
    """采集时间窗参数并完成基础校验。"""
    if window_name == "回播窗口":
        title = "回播窗口配置"
        summary = "当前回播窗口 before {0}s | after {1}s".format(
            ctx.logic.before,
            ctx.logic.after,
        )
        hint = "设置 Tag 前后回播窗口，总时长必须大于 0 秒"
        before_prompt = "回播开始前多少秒"
        after_prompt = "回播结束后多少秒"
    else:
        title = "切片时间窗配置"
        summary = "当前切片窗口 before {0}s | after {1}s".format(
            ctx.logic.before,
            ctx.logic.after,
        )
        hint = "设置 Tag 前后切片窗口，总时长必须大于 0 秒"
        before_prompt = "切片 tag 前多少秒"
        after_prompt = "切片 tag 后多少秒"

    ui.show_config_section(
        title,
        summary,
        hint,
    )
    while True:
        before = prompter.get_int_input(
            before_prompt,
            ctx.logic.before,
            history_name="slice_before",
        )
        after = prompter.get_int_input(
            after_prompt,
            ctx.logic.after,
            history_name="slice_after",
        )
        if before < 0:
            ui.show_input_feedback("before 不能小于 0")
            continue
        if before + after <= 0:
            ui.show_input_feedback("切片总时长必须大于 0 秒")
            continue
        ctx.logic.before = before
        ctx.logic.after = after
        return


def get_source_path_params(
    ctx,
    allow_remote: bool = True,
    preset_mode: Optional[int] = None,
) -> None:
    """采集数据源路径参数。"""
    mode_hint = "本地 / NAS"
    if allow_remote:
        mode_hint = "本地 / NAS / 车端"
    ui.show_config_section(
        "数据源配置",
        "选择输入模式并在需要时补充源路径",
        "可选模式: {0}".format(mode_hint),
    )
    if preset_mode is not None:
        ctx.logic.mode = int(preset_mode)
    else:
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
            history_name="source_root",
            path_completion=True,
        )


def get_export_path_params(ctx) -> None:
    """采集切片导出路径。"""
    ui.show_config_section(
        "导出路径配置",
        "当前导出路径: {0}".format(ctx.host.dest_root),
        "切片结果将写入这个目录",
    )
    ctx.host.dest_root = prompter.get_user_input(
        "切片导出路径 (限/media下)",
        ctx.host.dest_root,
        history_name="dest_root",
        path_completion=True,
    )


def get_path_params(ctx) -> None:
    """采集数据源路径和导出路径等与路径相关的配置。"""
    get_source_path_params(ctx)
    get_export_path_params(ctx)
    get_split_params(ctx)


def get_json_input() -> str:
    """获取 version.json 输入：支持路径拖拽和内容粘贴"""
    ui.show_config_section(
        "版本文件配置",
        "提供版本文件用于环境恢复",
        "支持直接粘贴路径或拖拽 version 文件",
    )
    while True:
        try:
            raw_data = prompter.prompt_text(
                "拖拽或粘贴输入 version 文件路径",
                history_name="version_path",
                path_completion=True,
            )
            if not raw_data:
                ui.show_input_feedback("输入为空，请重新输入")
                continue
            processed_path = raw_data.strip("'\"").replace("file://", "")
            processed_path = urllib.parse.unquote(processed_path)
            if os.path.isfile(processed_path):
                return processed_path
            ui.show_input_feedback(
                "version 文件路径不存在或不是文件，请重新输入",
                hint="支持直接粘贴本地文件路径或拖拽 version 文件",
            )
        except KeyboardInterrupt:
            ui.show_notice_section(
                "版本文件配置",
                "已取消",
                "WARN",
            )
            return ""


def update_dest_root(ctx, prompt: str) -> None:
    """更新导出根目录。"""
    ui.show_config_section(
        "目标路径配置",
        "当前路径: {0}".format(ctx.host.dest_root),
        "更新扫描或导出根目录",
    )
    ctx.host.dest_root = prompter.get_user_input(
        prompt,
        ctx.host.dest_root,
        history_name="dest_root",
        path_completion=True,
    )
