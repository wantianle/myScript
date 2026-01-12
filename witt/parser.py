import json
import logging
import os
import re
import sys
import subprocess
from pathlib import Path


README = Path(__file__).resolve().parents[1] / "docs" / "README"


def usage():
    subprocess.run(["less", README])


def get_user_input(prompt, default_value):
    val = input(f"{prompt} (默认 {default_value}): ").strip()
    return val if val else default_value


def get_json_input() -> str:
    print("请粘贴 version.json 内容或所在目录 (Ctrl+D 结束):")
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


def get_basic_params(config):
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


def get_path_params(config):
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
    # config["env"]["debug"] = (
    #     input("bash 调试模式 [y/N] (回车跳过): ").strip().lower() == "y"
    # )


def get_selected_indices(all_tasks, prompt="请输入要处理的序号"):
    """
    通用序号获取方法 带预览与重试逻辑
    :param all_tasks: 原始任务列表，用于获取长度和预览内容
    :param prompt: 输入提示词
    :return: 选中的任务对象列表
    """
    total_count = len(all_tasks)
    if total_count == 0:
        print("错误：任务列表为空。")
        return []

    while True:
        # print("\n" + "-" * 50)
        raw_input = input(
            f"{prompt}\n(单选: 1,3,5 | 范围: 2-6 | 全选: 0 | 排除: 0 5 7-15): "
        ).strip()

        # 预清洗：只保留数字、横杠、逗号、空白、换行
        clean_input = re.sub(r"[^\d\-,\s\n]", "", raw_input)

        # 分词
        tokens = [t for t in re.split(r"[,\s\n]+", clean_input) if t]

        if not tokens:
            print("输入为空，请重新输入。")
            continue

        full_set = set(range(1, total_count + 1))
        result_set = set()

        # 核心解析逻辑
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
                continue

        # 4. 过滤越界序号并排序
        final_ids = sorted([i for i in result_set if 1 <= i <= total_count])
        if not final_ids:
            print("未选中任何有效序号，请检查输入是否超限。")
            continue

        # 5. 预览逻辑
        preview_limit = 10
        display_ids = final_ids[:preview_limit]
        preview_str = ", ".join(map(str, display_ids))
        if len(final_ids) > preview_limit:
            preview_str += f" ..."

        print(f"选中待处理序号: [{preview_str}(共 {len(final_ids)} 项)]")

        # 6. 用户确认
        confirm = input("确认执行？[y/N] (回车确认): ").strip().lower()
        if confirm in ["y", "yes", ""]:
            return [all_tasks[i - 1] for i in final_ids]
        else:
            print("已取消...")
