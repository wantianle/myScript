import subprocess
import sys
import importlib.util

def bootstrap():
    if importlib.util.find_spec("pip") is None:
        print("未检测到 pip，正在尝试紧急引导(ensurepip)...")
        try:
            # 尝试通过内置模块安装 pip
            subprocess.check_call(
                [sys.executable, "-m", "ensurepip", "--default-pip"],
                stdout=subprocess.DEVNULL,
            )
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "--upgrade", "pip"],
                stdout=subprocess.DEVNULL,
            )
            print("pip 安装成功！")
        except Exception:
            print("错误: 系统缺少 pip 且自动修复失败。")
            print("请执行以下命令安装 pip 后重试:")
            print(
                "   sudo apt update && sudo apt install python3-pip"
            )
            sys.exit(1)
    dependencies = [
        ("pyyaml", "yaml"),
        ("alive-progress", "alive_progress"),
    ]
    missing = []
    for pkg, imp in dependencies:
        try:
            __import__(imp)
        except ImportError:
            missing.append(pkg)

    if missing:
        print(f"检测到环境缺失，正在为你自动准备: {', '.join(missing)}")
        try:
            subprocess.check_call(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    *missing,
                    "-i",
                    "https://pypi.tuna.tsinghua.edu.cn/simple",
                ]
            )
            print("环境就绪！继续启动...\n")
        except Exception as e:
            print(f"❌ 自动安装失败，请手动执行: pip install {' '.join(missing)}")
            print(f"错误详情: {e}")
            sys.exit(1)


import yaml
import os
import json
import logging
import copy
import traceback
from pathlib import Path
from datetime import datetime, timedelta
from core.context import TaskContext
from core.docker_adapter import DockerExecutor
from core.record_manager import RecordManager
from core.ssh_adapter import SSHExecutor
from core.task_executor import TaskExecutor
from scripts.dowload_record import RecordDownloader


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = BASE_DIR / "config" / "settings.yaml"
# ==================== 辅助函数  ====================

def load_config(config_path: Path = DEFAULT_CONFIG_PATH) -> dict:
    """标准配置加载函数，带异常处理"""
    if not config_path.exists():
        print(f"致命错误: 配置文件不存在于 {config_path}")
        sys.exit(1)
    try:
        return yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"解析配置文件失败: {e}")
        sys.exit(1)


def extract_manifest(manifest: Path) -> list[str]:
    """
    解析路径
    """
    parts = []
    if not manifest.exists() or manifest.stat().st_size == 0:
        logging.error("未发现匹配的录制数据。")
        return parts
    for line in manifest.read_text(encoding="utf-8").splitlines():
        parts.append(line.strip())
    return parts


def get_json_input():
    print("请粘贴 JSON 数据或输入文件路径 (完成后按 Ctrl+D 结束):")
    try:
        raw_input = sys.stdin.read().strip()
        if not raw_input:
            print("错误: 输入内容为空")
            return None
        if os.path.isdir(raw_input):
            return raw_input
        data = json.dumps(json.loads(raw_input))
        return data

    except json.JSONDecodeError as e:
        print(f"JSON 解析错误: 请检查粘贴的内容是否完整。具体错误: {e}")
        return None
    except Exception as e:
        print(f"发生意外错误: {e}")
        return None


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
        config["env"]["soc"] = soc
        config["host"]["dest_root"] = (
            input(f"本地导出路径 (默认 {config['host']['dest_root']}): ").strip()
            or config["host"]["dest_root"]
        )

        print("\n查询模式: [1]本地(默认) [2]NAS [3]远程")
        choice = input("选择: ").strip() or "1"
        if choice != "2" and choice != "3":
            config["host"]["local_path"] = (
                input("输入本地数据根路径(仅/media，默认/media/data): ").strip()
                or config["host"]["local_path"]
            )
        config["env"]["mode"] = int(choice)
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
            "lb": int(lb),
            "lf": int(lf),
        }


# ==================== 核心功能 ====================

def task_query(executor, ui):
    logging.info(">>> 执行数据检索与同步 (find_record)...")
    find_args = [
        "-s",
        ui["soc"],
        "-b",
        str(ui["lb"]),
        "-f",
        str(ui["lf"]),
    ]
    executor.run_find_record(find_args)


def task_compress(record_mgr, host_path: Path, config):
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
        indices = []
        for part in user_in.split(","):
            try:
                if "-" in part.strip():
                    start_str, end_str = part.split("-")
                    start, end = int(start_str), int(end_str)
                    indices.extend(range(start - 1, end))
                else:
                    indices.append(int(part) - 1)
            except ValueError:
                print(f"输入无效 {part}")
                return
        indices = sorted(list(set(indices)))
        to_delete = [channels[i]["name"] for i in indices if 0 <= i < len(channels)]
    new_blacklist = list(set(config["logic"].get("blacklist") or [] + to_delete))
    config["logic"]["blacklist"] = new_blacklist


def task_slice(record_mgr, input_path: Path, lb, lf, config, tag_dt):
    """时间截取切片"""
    tag_start = tag_dt - timedelta(seconds=lb)
    tag_end = tag_dt + timedelta(seconds=lf)

    output_path = f"{input_path}.lean"
    info = record_mgr.get_info(str(input_path))
    if info["begin"]:
        # 计算重叠时间窗口
        start, end = max(info["begin"], tag_start), min(info["end"], tag_end)
        if start < end:
            record_mgr.split(
                str(input_path),
                str(output_path),
                start,
                end,
                config["logic"]["blacklist"],
            )


def task_download(session):
    """
    读取清单 -> 用户选择 -> 执行下载
    """
    downloader = RecordDownloader(session.ctx)
    downloader.download_tasks()


def task_sync(executor, input):
    """
    同步环境
    """
    executor.run_restore_env(input)

# ==================== 运行时会话 ====================


class AppSession:
    """初始化并持有所有执行对象，减少重复创建"""

    def __init__(self, config, target_date, vehicle, ui=None):
        self.config = config
        if ui:
            self.ui = ui

        self.ctx = TaskContext(self.config, vehicle, target_date)
        self.ctx.setup_logger()

        if self.config["env"].get("mode") == 3:
            from core.ssh_adapter import SSHExecutor
            self.backend = SSHExecutor(self.config)
            # logging.info(">>> 启用【远程后端】: 直接在车机执行处理指令")
        else:
            self.backend = DockerExecutor(self.config)
            # logging.info(">>> 启用【本地后端】: 在本地 Docker 执行处理指令")
        self.record_mgr = RecordManager(self.backend)
        self.executor = TaskExecutor(self.ctx)


# ==================== 工作流 ====================


def run_full_pipeline():
    config = load_config()
    target_date, vehicle = CLIHandler.get_basic_info(config)
    ui = CLIHandler.get_workflow_params(config, target_date, vehicle)
    session = AppSession(config, target_date, vehicle, ui)
    task_query(session.executor, ui)
    parts = extract_manifest(session.ctx.manifest_path)
    if input("是否压缩 Record? [y/N]: ").lower() == "y":
        task_compress(
            session.record_mgr, Path(parts[0].split("|")[2].split()[0]), config
        )
    for item in parts:
        tag_dt, tag, paths = item.split("|")
        tag_dt = datetime.strptime(tag_dt, "%Y-%m-%d %H:%M:%S")
        sub_paths = paths.split()
        print(f"\n>>> 正在处理: {tag} {tag_dt}")
        for p in sub_paths:
            task_slice(
                session.record_mgr,
                Path(p),
                ui["lb"],
                ui["lf"],
                config,
                tag_dt)
    task_download(session)


# ==================== 主菜单  ====================


def main_menu():
    master_config = load_config()

    while True:
        print("\n" + "=" * 50)
        print("               witt  v0.7")
        print("            What Is That Tag?")
        print("=" * 50)
        print("  1. [全流程] 查询 -> 压缩 -> 切片 -> 打包")
        print("  2. [仅查询] 数据检索")
        print("  3. [仅压缩] 指定文件 Channel 过滤")
        print("  4. [仅切片] 指定目录对时间切片")
        print("  5. [数据回灌] 本地环境数据回灌 ")
        print("  q. 退出")
        print("=" * 50)

        choice = input("请选择操作: ").strip().lower()
        config = copy.deepcopy(master_config)

        if choice == "1":
            run_full_pipeline()
        elif choice in ("2", "3", "4", "5"):
            target_date, vehicle = CLIHandler.get_basic_info(config)
            session = AppSession(config, target_date, vehicle)
            if choice == "2":
                ui = CLIHandler.get_workflow_params(config, target_date, vehicle)
                session = AppSession(config, target_date, vehicle, ui)
                task_query(session.executor, ui)
            elif choice == "3":
                target_path=Path(input("需要压缩的 record 文件路径: ").strip())
                info = session.record_mgr.get_info(str(target_path))
                task_compress(
                    session.record_mgr,
                    target_path,
                    config,
                )
                tag_dt = datetime.strptime(f"{info.get('begin')}", "%Y-%m-%d-%H:%M:%S}")
                task_slice(
                    session.record_mgr,
                    target_path,
                    0,
                    120,
                    config,
                    tag_dt,
                )
            elif choice == "4":
                lb = (
                    input(f"回溯秒数 (默认 {config['logic']['lookback']}): ").strip()
                    or config["logic"]["lookback"]
                )
                lf = (
                    input(f"前瞻秒数 (默认 {config['logic']['lookfront']}): ").strip()
                    or config["logic"]["lookfront"]
                )
                target = Path(input("需要切片的 record 文件所在目录: ").strip())
                time_raw = input("基准时间 (HHMMSS): ").strip()
                tag_dt = datetime.strptime(f"{target_date}{time_raw}", "%Y%m%d%H%M%S")
                for f in target.glob("*.record*"):
                    task_slice(
                        session.record_mgr,
                        f,
                        lb,
                        lf,
                        config,
                        tag_dt,
                    )
            elif choice == "5":
                task_sync(
                    session.executor,
                    get_json_input(),
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
