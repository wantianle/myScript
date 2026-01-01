import yaml
import logging
import sys
import re
from pathlib import Path
from datetime import datetime, timedelta
import subprocess
import traceback
from core.context import TaskContext
from core.docker_adapter import DockerExecutor
from core.record_manager import RecordManager
from core.task_executor import TaskExecutor

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = BASE_DIR / "config" / "settings.yaml"
# ==================== 辅助函数  ====================


def load_config(config_path: Path = DEFAULT_CONFIG_PATH) -> dict:
    """标准配置加载函数，带异常处理"""
    if not config_path.exists():
        print(f"致命错误: 配置文件不存在于 {config_path}")
        sys.exit(1)
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"解析配置文件失败: {e}")
        sys.exit(1)


def extract_tag_time(readme_path: Path) -> datetime | None:
    """从 README.md 中提取精准的事件触发时间"""
    if not readme_path.exists():
        return None
    try:
        content = readme_path.read_text(encoding="utf-8")
        # 匹配格式: 2025-12-27 16:28:10
        match = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", content)
        return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S") if match else None
    except Exception as e:
        logging.error(f"解析 README 失败: {e}")
        return None


def find_soc_dir(tag_path: Path, soc: str) -> Path | None:
    """在 tag 目录下定位以 _{soc} 结尾的子目录"""
    if not tag_path.exists():
        return None
    for item in tag_path.iterdir():
        if item.is_dir() and item.name.endswith(f"_{soc}"):
            return item
    return None


def is_record_file(path: Path) -> bool:
    """判断是否为 record 数据文件 (包含 .record 且不是切片或压缩后的副本)"""
    name = path.name
    return ".record" in name and ".sliced" not in name and ".lean" not in name


# ==================== 交互处理 ====================


class CLIHandler:
    """负责所有与用户的交互输入"""

    @staticmethod
    def get_basic_info(config):
        print(f"\n{' 基本信息确认 ':-^30}")
        target_date = (
            input(
                f"请输入日期 (YYYYMMDD,可精确到小时, 默认 {config['env']['target_date']}): "
            ).strip()
            or config["env"]["target_date"]
        )
        vehicle = (
            input(f"请输入车辆名 (默认 {config['env']['vehicle']}): ").strip()
            or config["env"]["vehicle"]
        )
        return target_date, vehicle

    @staticmethod
    def get_workflow_params(config, target_date, vehicle):
        soc = (
            input(f"目标 SOC 文件夹 (默认 {config['env']['soc']}): ").strip()
            or config["env"]["soc"]
        )
        export_root = (
            input(f"本地导出路径 (默认 {config['host']['dest_root']}): ").strip()
            or config["host"]["dest_root"]
        )

        print("\n查询模式: [1]本地(默认) [2]NAS [3]远程")
        local_data = []
        choice = input("选择: ").strip() or "1"
        if choice != "2" and choice != "3":
            path = (
                input("输入本地数据根路径(仅/media，默认/media/data): ").strip()
                or config["host"]["local_path"]
            )
            local_data = ["-p", path]
        config["env"]["mode"] = choice
        lb = (
            input(f"回溯秒数 (默认 {config['logic']['lookback']}): ").strip()
            or config["logic"]["lookback"]
        )
        lf = (
            input(f"前瞻秒数 (默认 {config['logic']['lookfront']}): ").strip()
            or config["logic"]["lookfront"]
        )
        config["env"]["debug"] = (
            input("bash 调试模式 [y/N default: n]: ").strip().lower() == "y"
        )
        return {
            "target_date": target_date,
            "vehicle": vehicle,
            "soc": soc,
            "export_dir": export_root,
            "local_data": local_data,
            "lb": int(lb),
            "lf": int(lf),
        }


# ==================== 核心功能 ====================


def task_query(executor, ui):
    logging.info(">>> 执行数据检索与同步 (find_record)...")
    find_args = ui["local_data"] + [
        "-s",
        ui["soc"],
        "-d",
        ui["export_dir"],
        "-b",
        str(ui["lb"]),
        "-f",
        str(ui["lf"]),
    ]
    executor.run_find_record(find_args)


def task_download(session, ui):
    """
    读取清单 -> 用户选择 -> 执行下载
    """
    task_query(session.executor, ui)

    manifest = session.ctx.manifest_path
    if not manifest.exists() or manifest.stat().st_size == 0:
        logging.error("未发现匹配的录制数据。")
        return

    print(f"\n{' 待下载任务清单 ':=^50}")
    print(f"{'ID':<4} | {'Tag':<20} | {'Time'}")
    print("-" * 50)

    with open(manifest, "r", encoding="utf-8") as f:
        lines = f.readlines()
        for line in lines:
            # 假设清单格式: ID|Time|Msg|Files
            parts = line.strip().split("|")
            if len(parts) >= 3:
                print(f"{parts[0]:<4} | {parts[1]:<20} | {parts[2]}")

    selection = input("\n请输入下载序号 (多个逗号分隔, 0全选, 回车跳过): ").strip()
    if not selection:
        return

    session.executor.run_download_record(selection)


def task_compress(record_mgr, host_path: Path):
    """Channel 过滤压缩"""
    print(f"\n[分析文件]: {host_path.name}")
    info = record_mgr.get_info(str(host_path))
    channels = info.get("channels", [])

    if not channels:
        logging.warning("未发现有效 Channel，跳过压缩")
        return

    print("-" * 72)
    print(f"{'ID':<4} | {'Channel Name':<55} | {'Messages'}")
    print("-" * 72)
    for i, ch in enumerate(channels, 1):
        print(f"{i:<4} | {ch['name']:<55} | {ch['count']}")

    user_in = input("\n[操作]: 回车跳过 | '0'全删 | 序号(如1,3)删除指定: ").strip()
    if not user_in:
        return

    to_delete = [c["name"] for c in channels] if user_in == "0" else []
    if not to_delete:
        try:
            indices = [int(x.strip()) - 1 for x in user_in.split(",")]
            to_delete = [channels[i]["name"] for i in indices if 0 <= i < len(channels)]
        except ValueError:
            print("输入无效，跳过压缩")
            return

    output_path = host_path / f".sliced"
    if info["begin"]:
        record_mgr.split(
            str(host_path), str(output_path), info["begin"], info["end"], to_delete
        )
        logging.info(f"压缩完成: {output_path.name}")


def task_slice(record_mgr, tag_dir: Path, soc_dir: Path, ui, config, manual_dt=None):
    """时间截取切片"""
    tag_dt = manual_dt or extract_tag_time(tag_dir / "README.md")
    if not tag_dt:
        logging.warning(f"无法获取时间基准点: {tag_dir.name}")
        return

    t_start = tag_dt - timedelta(seconds=ui["lb"])
    t_end = tag_dt + timedelta(seconds=ui["lf"])

    for f in filter(is_record_file, soc_dir.iterdir()):

        output_file = soc_dir / f"{f.name}.sliced"
        info = record_mgr.get_info(str(f))

        if info["begin"]:
            # 计算重叠时间窗口
            ov_start, ov_end = max(info["begin"], t_start), min(info["end"], t_end)
            if ov_start < ov_end:
                record_mgr.split(
                    str(f),
                    str(output_file),
                    ov_start,
                    ov_end,
                    config["logic"]["blacklist"],
                )


def task_sync(executor, tag_dir: Path):
    v_json = executor.find_version_json(str(tag_dir))
    if v_json:
        executor.run_restore_env(v_json)
    else:
        logging.warning(f"未发现版本信息: {tag_dir.name}")


# ==================== 运行时会话 ====================


class AppSession:
    """初始化并持有所有执行对象，减少重复创建"""

    def __init__(self, config, target_date, vehicle, ui=None):
        self.config = config
        if ui:
            self.config["host"]["dest_root"] = ui["export_dir"]
            self.ui = ui

        self.ctx = TaskContext(self.config, vehicle, target_date)
        self.ctx.setup_logger()

        self.docker_adapter = DockerExecutor(self.config)
        self.record_mgr = RecordManager(self.docker_adapter)
        self.executor = TaskExecutor(self.ctx)


# ==================== 工作流 ====================


def run_full_pipeline():
    config = load_config()

    target_date, vehicle = CLIHandler.get_basic_info(config)
    ui = CLIHandler.get_workflow_params(config, target_date, vehicle)

    workflow_cfg = {
        "compress": input("是否压缩 Record? [y/N]: ").lower() == "y",
        "slice": input("是否切片? [y/N]: ").lower() == "y",
        "sync": input("是否同步环境? [y/N]: ").lower() == "y",
    }

    session = AppSession(config, target_date, vehicle, ui)

    task_query(session.executor, ui)

    work_dir = Path(session.ctx.work_dir)
    if not work_dir.exists():
        return

    for tag_dir in filter(lambda p: p.is_dir(), work_dir.iterdir()):
        soc_dir = find_soc_dir(tag_dir, ui["soc"])
        if not soc_dir:

            continue

        print(f"\n>>> 正在处理: {tag_dir.name}")

        if workflow_cfg["compress"]:
            for f in filter(is_record_file, soc_dir.iterdir()):
                task_compress(session.record_mgr, f)

        if workflow_cfg["slice"]:
            task_slice(session.record_mgr, tag_dir, soc_dir, ui, config)

        if workflow_cfg["sync"]:
            task_sync(session.executor, tag_dir)


# ==================== 主菜单  ====================


def main_menu():
    config = load_config()

    while True:
        print("\n" + "=" * 50)
        print("                  🚀  SNAP v0.4")
        print("        Search, Normalize, Analyze, Process")
        print("=" * 50)
        print("  1. [全流程] 查询 -> 压缩 -> 切片 -> 回灌")
        print("  2. [仅查询] 数据检索与下载")
        print("  3. [仅压缩] 指定文件 Channel 过滤")
        print("  4. [仅切片] 指定目录对时间切片")
        print("  5. [仅环境] docker 环境版本同步")
        print("  q. 退出")
        print("=" * 50)

        choice = input("请选择操作: ").strip().lower()

        if choice == "1":
            run_full_pipeline()
        elif choice in ("2", "3", "4", "5"):
            target_date, vehicle = CLIHandler.get_basic_info(config)
            if choice == "2":
                ui = CLIHandler.get_workflow_params(config, target_date, vehicle)
                session = AppSession(config, target_date, vehicle, ui)
                task_query(session.executor, ui)
            elif choice == "3":
                session = AppSession(config, target_date, vehicle)
                task_compress(
                    session.record_mgr,
                    Path(input("需要压缩的 record 文件路径: ").strip()),
                )
            elif choice == "4":
                ui = CLIHandler.get_workflow_params(config, target_date, vehicle)
                target = Path(input("需要切片的 record 文件所在目录: ").strip())
                time_raw = input("基准时间 (HHMMSS): ").strip()
                tag_dt = datetime.strptime(f"{target_date}{time_raw}", "%Y%m%d%H%M%S")
                session = AppSession(config, target_date, vehicle, ui)
                task_slice(
                    session.record_mgr,
                    target,
                    find_soc_dir(target, ui["soc"]) or target,
                    ui,
                    config,
                    manual_dt=tag_dt,
                )
            elif choice == "5":
                session = AppSession(config, target_date, vehicle)
                task_sync(
                    session.executor, Path(input("version.json 所在目录: ").strip())
                )
        elif choice == "q":
            sys.exit(0)


if __name__ == "__main__":
    try:
        main_menu()
    except KeyboardInterrupt:
        sys.exit(0)
    # except subprocess.CalledProcessError as e:
    #     logging.error(
    #         f"命令执行失败: {' '.join(e.cmd if isinstance(e.cmd, list) else [e.cmd])}"
    #     )
    #     sys.exit(1)
    # except Exception as e:
    #     print(f"\n\033[1;31m[CRITICAL] 发生内部程序错误: {e}\033[0m")
    #     print(f"详情请查看日志文件。")
    #     logging.error("--- 捕获到未处理的 Python 异常堆栈 ---")
    #     logging.exception(e)
    #     sys.exit(1)
