import json
import logging
import os
import re
import sys
import subprocess
import traceback
from core.seesion import AppSession
from utils import cli
from pathlib import Path
from utils import handles

README = Path(__file__).parent / "README"


def usage():
    subprocess.run(["less", README])


def get_user_input(prompt, default_value):
    val = input(f"{prompt} (默认 {default_value}): ").strip()
    return val if val else default_value


def get_json_input() -> str:
    print(
        "请粘贴 version.json 内容或所在目录 (Ctrl+D 结束):"
    )
    try:
        input = sys.stdin.read().strip()
        if not input:
            logging.error("错误: 输入内容为空")
            sys.exit(1)
        if os.path.isdir(input):
            return input
        return json.dumps(json.loads(input))

    except json.JSONDecodeError as e:
        logging.error(f"JSON 解析错误: 请检查粘贴的内容是否完整。具体错误: {e}")
        raise e
    except Exception as e:
        logging.error(f"发生意外错误: {e}")
        raise e


def get_basic_info(config):
    print(f"\n{' 基本信息确认 ':-^30}")
    config["logic"]["target_date"] = get_user_input(
        "请输入日期 <YYYYMMDD[hh]>", config["logic"]["target_date"]
    )
    config["logic"]["vehicle"] = get_user_input(
        "请输入车辆名", config["logic"]["vehicle"]
    )


def get_split_params(config):
    config["logic"]["before"] = int(
        get_user_input(
            "查询/切片 tag 之前多少秒(before 支持负数)", config["logic"]["before"]
        )
    )
    config["logic"]["after"] = int(
        get_user_input(
            "查询/切片 tag 之后多少秒(after 支持负数且|after|>|before|)",
            config["logic"]["after"],
        )
    )


def get_workflow_params(config):
    inx = input("选择 [1] soc1 [2] soc2 (默认 1): ").strip()
    config["logic"]["soc"] = (inx in ("1", "2") and f"soc{inx}") or config["logic"][
        "soc"
    ]
    config["host"]["dest_root"] = get_user_input(
        "指定本地导出路径 (仅限/media下)", config["host"]["dest_root"]
    )
    print("\n查询模式: [1]本地(默认) [2]NAS [3]远程")
    choice = input("选择: ").strip() or "1"
    if choice != "2" and choice != "3":
        config["host"]["local_path"] = get_user_input(
            "本地数据根路径(仅限/media下)", config["host"]["local_path"]
        )
    config["env"]["mode"] = int(choice)
    get_split_params(config)
    config["env"]["debug"] = (
        input("bash 调试模式 [y/N] (回车跳过): ").strip().lower() == "y"
    )

def run_full_pipeline(session: AppSession):
    cli.get_basic_info(session.config)
    cli.get_workflow_params(session.config)
    try:
        session.task_query()
        task_list = handles.parse_manifest(session.ctx.manifest_path)
        if input("是否压缩 Record? [y/N] (回车跳过): ").lower() == "y":
            # 这里怎么简化，我只需要channel名单去过滤信息
            session.task_compress(Path(task_list[0]["paths"][0]))
        for task in task_list:
            _, time, name, paths = task["id"], task["time"], task["name"], task["paths"]
            tag_dt = handles.str_to_time(time)
            print(f"\n>>> 正在处理: {name} {tag_dt}")
            for f in paths:
                session.task_slice(Path(f), tag_dt)
        session.task_download()
        if input("\n是否立即回播数据? [y/N] (回车跳过): ").lower() == "y":
            task_player_workflow(session)
    except Exception as e:
        logging.error(f"全流程执行失败: {e}")
        logging.debug(traceback.format_exc())
        sys.exit(1)


def task_player_workflow(session: AppSession):
    while True:
        library = session.player.get_library()
        if not library:
            print("本地没有任何 Record 数据。")
            return

        print(f"\n{' ID ':<4} | {' Vehicle ':<10} | {' Time ':<20} | {' Tag Message '}")
        print("-" * 65)
        count = 1
        for entry in library:
            if (
                entry["date"] == session.config["logic"]["target_date"]
                and entry["vehicle"] == session.config["logic"]["vehicle"]
            ):
                print(
                    f" {count:<4} | {entry['vehicle']:<10} | {entry['time']:<20} | {entry['tag']}"
                )
                count += 1
        tag_idx = input("\n请选择播放序号 (回车取消): ").strip()
        if not tag_idx:
            return
        selected_tag = library[int(tag_idx) - 1]

        available_socs = list(selected_tag["socs"].keys())
        for i, s in enumerate(available_socs, 1):
            print(f"  [{i}] {s}")

        soc_idx = input("选择 (默认 1): ").strip() or "1"
        soc_key = available_socs[int(soc_idx) - 1]
        target_records = selected_tag["socs"][soc_key]
        range_in = (
            input("输入播放范围(秒) ('0' '5' '10-30' 默认全量播放): ").strip() or "0"
        )

        start_s, end_s = 0, 0
        if range_in:
            try:
                nums = re.findall(r"\d+", range_in)
                if len(nums) >= 2:
                    start_s, end_s = int(nums[0]), int(nums[1])
                elif len(nums) == 1:
                    start_s = int(nums[0])
            except ValueError:
                print("输入错误，开始全量播放...")

        session.player.play(target_records, start_s, end_s)
