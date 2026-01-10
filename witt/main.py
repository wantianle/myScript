import re
import sys
import logging
import subprocess
import traceback
from utils import cli
from pathlib import Path
from datetime import timedelta
from core.context import TaskContext
from core.docker_adapter import DockerAdapter
from core.record_manager import RecordManager
from core.ssh_adapter import SSHAdapter
from core.task_executor import TaskExecutor
from core.player import RecordPlayer
from core.dowload_record import RecordDownloader
from utils import handles

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = BASE_DIR / "config" / "settings.yaml"
SET_UP_ENV = BASE_DIR / "scripts" / "setup_env.sh"
# ==================== 运行时会话 ====================

class AppSession:
    """初始化并持有所有执行对象，减少重复创建"""
    def __init__(self):
        self.ctx = TaskContext(DEFAULT_CONFIG_PATH)
        self.config = self.ctx.config
        if self.config["env"].get("mode") == 3:
            self.backend = SSHAdapter(self.ctx)
        else:
            self.backend = DockerAdapter(self.ctx)
        self.record_mgr = RecordManager(self.backend)
        self.executor = TaskExecutor(self.ctx)

    def task_query(self):
        self.ctx.setup_logger()
        logging.info(">>> 执行数据检索与同步 (find_record)...")
        self.executor.run_find_record()

    def task_compress(self, record_path: Path):
        """Channel 过滤压缩"""
        self.ctx.setup_logger()
        info = self.record_mgr.get_info(str(record_path))
        channels = info.get("channels", [])
        if not channels:
            logging.warning("未发现有效 Channel，跳过压缩")
            return
        print(f"\n>>> 分析文件: {record_path.name}")
        print(f"bgin: {info.get('begin_time')}   end: {info.get('end_time')}")
        print("-" * 72)
        print(f"{'ID':<4} | {'Channel Name':<55} | {'Messages'}")
        print("-" * 72)
        for i, ch in enumerate(channels, 1):
            print(f"{i:<4} | {ch['name']:<55} | {ch['count']}")

        user_in = input(
            "\n[操作]: 回车跳过 | '0'全删 | 序号(如1,3,20-28)删除指定 channel: "
        ).strip()
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
        new_blacklist = list(
            set(self.config["logic"].get("blacklist") or [] + to_delete)
        )
        self.config["logic"]["blacklist"] = new_blacklist
        logging.info(f">>> 执行数据压缩: {new_blacklist}")

    def task_slice(self, input_path: Path, tag_dt=None):
        """时间截取切片"""
        self.ctx.setup_logger()
        before = self.config["logic"]["before"]
        after = self.config["logic"]["after"]
        tag_start, tag_end = None, None
        if tag_dt :
            tag_start = tag_dt - timedelta(seconds=before)
            tag_end = tag_dt + timedelta(seconds=after)
        success = self.record_mgr.split(
            host_in=str(input_path),
            # host_out=str(input_path.with_suffix(".split")),
            start_dt=tag_start,
            end_dt=tag_end,
            blacklist=self.config["logic"]["blacklist"],
        )

        if not success:
            logging.warning(f">>> [Skip] 文件 {input_path} 可能已损坏，已自动跳过。")

    def task_download(self):
        """
        读取清单 -> 用户选择 -> 执行下载
        """
        downloader = RecordDownloader(self.ctx)
        downloader.download_tasks()

    def task_sync(self):
        """
        同步环境
        """
        self.executor.run_restore_env()


# ==================== 工作流 ====================


def run_full_pipeline(session: AppSession):
    cli.get_basic_info(session.config)
    cli.get_workflow_params(session.config)
    try:
        session.task_query()
        tasks_list = handles.parse_manifest(session.ctx.manifest_path)
        if input("是否压缩 Record? [y/N] (回车跳过): ").lower() == "y":
            # 这里怎么简化，我只需要channel名单去过滤信息
            session.task_compress(Path(tasks_list[0]["files"][0]))
        for task in tasks_list:
            _, time, name, files = task["id"], task["time"], task["name"], task["files"]
            tag_dt = handles.str_to_time(time)
            print(f"\n>>> 正在处理: {name} {tag_dt}")
            for f in files:
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
        player = RecordPlayer(session)
        library = player.get_library()

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

        player.play(target_records, start_s, end_s)


# ==================== 主菜单  ====================


def main_menu():
    while True:
        session = AppSession()
        config = session.config
        print("\n" + "=" * 50)
        print("               witt  v1.0")
        print("            What Is That Tag?")
        print("=" * 50)
        print("  1. 三端查询 -> 压缩/切片/下载 -> 同步环境回放")
        print("  2. [仅查询] 查询 tag 对应 record 文件")
        print("  3. [仅压缩] 指定文件过滤 Channel")
        print("  4. [仅切片] 指定目录对时间切片")
        print("  5. [仅同步] 同步本地 docker 环境")
        print("  6. [仅回播] 查询并回播已处理数据")
        print("  q. 退出")
        print("=" * 50)
        choice = input("请选择操作: ").strip().lower()
        if choice == "1":
            run_full_pipeline(session)
        elif choice in ("2", "3", "4", "5", "6"):
            cli.get_basic_info(config)
            if choice == "2":
                cli.get_workflow_params(config)
                session.task_query()
            elif choice == "3":
                target_path = Path(input("需要压缩的 record 文件完整路径: ").strip())
                session.task_compress(target_path)
                session.task_slice(target_path)
            elif choice == "4":
                cli.get_split_params(config)
                target = Path(input("需要切片的 record 文件的目录路径: ").strip())
                time_raw = input("基准时间 (HHMMSS): ").strip()
                tag_dt = handles.str_to_time(
                    f"{config['logic']['target_date'][:8]}{time_raw}"
                )
                for f in target.glob("*.record*"):
                    session.task_slice(f, tag_dt)
            elif choice == "5":
                config["logic"]["version_json"] = cli.get_json_input() or config["logic"][
                    "version_json"
                ]
                session.task_sync()
            elif choice == "6":
                print(">>> 进入数据回播...")
                print("回播数据路径结构: <data_root>/<vehicle>/<date>/<tag>/<soc>")
                print("例如: '/media/road_data/XZB600011/20260101/急刹/soc1/xxxx.record.xxxx'\n")
                config["host"]["dest_root"] = cli.get_user_input(
                    "请输入回播数据根目录(仅限/media下)", config["host"]["dest_root"]
                )
                task_player_workflow(session)
        elif choice == "q":
            sys.exit(0)


if __name__ == "__main__":
    try:
        subprocess.run(["bash", SET_UP_ENV],check=True)
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
    #     logging.debug("--- 捕获到未处理的 Python 异常堆栈 ---")
    #     logging.debug(e)
    #     sys.exit(1)
