import logging
import re
from core.context import TaskContext
from core.forDocker import DockerAdapter
from core.recorder import Recorder
from core.forSSH import SSHAdapter
from core.runner import ScriptRunner
from core.player import RecordPlayer
from core.dowloader import RecordDownloader
from utils import cli
from utils import handles
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = BASE_DIR / "config" / "settings.yaml"


class AppSession:
    """初始化并持有所有执行对象，减少重复创建"""

    def __init__(self):
        self.ctx = TaskContext(DEFAULT_CONFIG_PATH)
        if self.ctx.config["env"].get("mode") == 3:
            self.executor = SSHAdapter(self.ctx.config)
        else:
            self.executor = DockerAdapter(self.ctx)
        self.recorder = Recorder(self.executor)
        self.runner = ScriptRunner(self.ctx)
        self.downloader = RecordDownloader(self)
        self.player = RecordPlayer(self)
        self.before = self.ctx.config["logic"]["before"]
        self.after = self.ctx.config["logic"]["after"]

    def record_query(self):
        self.ctx.setup_logger()
        logging.info(">>> 执行数据检索查询...")
        self.runner.run_find_record()

    def record_compress(self, record_path: Path):
        """Channel 过滤压缩"""
        self.ctx.setup_logger()
        info = self.recorder.get_info(str(record_path))
        channels = info.get("channels", [])
        print("-" * 72)
        print(f"{'ID':<4} | {'Channel Name':<55} | {'Messages'}")
        print("-" * 72)
        for i, ch in enumerate(channels, 1):
            print(f"{i:<4} | {ch['name']:<55} | {ch['count']}")
        selected_indices = cli.get_selected_indices(channels)
        selected_channels = [c["name"] for c in selected_indices]
        self.ctx.config["logic"]["blacklist"] = selected_channels
        logging.info(
            f">>> 执行数据压缩切片 ==> 取 tag 前 {self.before}s 后{self.after}s 删除 channels: {selected_channels}"
        )

    def record_slice(self, input_path: Path, tag_dt=None):
        """时间截取切片"""
        self.ctx.setup_logger()
        tag_start, tag_end = None, None
        if tag_dt:
            tag_start = tag_dt - timedelta(seconds=self.before)
            tag_end = tag_dt + timedelta(seconds=self.after)
        success = self.recorder.split(
            host_in=str(input_path),
            # host_out=str(input_path.with_suffix(".split")),
            start_dt=tag_start,
            end_dt=tag_end,
            blacklist=self.ctx.config["logic"]["blacklist"],
        )
        if not success:
            logging.warning(f">>> [Skip] 文件 {input_path} 可能已损坏，切片失败。")
            return False
        else:
            return True

    def record_download(self, selected_list):
        """
        读取清单 -> 用户选择 -> 执行下载
        """
        self.ctx.setup_logger()
        self.downloader.download_record(selected_list)

    def task_sync(self):
        """
        同步环境
        """
        self.ctx.setup_logger()
        self.runner.run_restore_env()

    def task_play(self):
        self.ctx.setup_logger()
        while True:
            library = self.player.get_library()
            if not library:
                logging.warning("本地没有任何 Record 数据")
                return

            print(
                f"\n{' ID ':<4} | {' Vehicle ':<10} | {' Time ':<20} | {' Tag Message '}"
            )
            print("-" * 65)
            count = 1
            for entry in library:
                if (
                    entry["date"] == self.ctx.target_date
                    and entry["vehicle"] == self.ctx.vehicle
                ):
                    # tag_dir = self.ctx.work_dir / entry["tag"]
                    # print(
                    #     f" {count:<4} | {entry['vehicle']:<10} | {entry['time']:<20} | ", end=""
                    # )
                    print(
                        f" {count:<4} | {entry['vehicle']:<10} | {entry['time']:<20} | {entry['tag']}"
                    )
                    # handles.print_tree(tag_dir)
                    count += 1
            tag_idx = input("\n请选择播放序号 (回车取消): ").strip()
            if not tag_idx:
                return
            selected_tag = library[int(tag_idx) - 1]

            socs = list(selected_tag["socs"].keys())
            for i, s in enumerate(socs, 1):
                print(f"  [{i}] {s}")

            soc_idx = input("选择 (默认 1): ").strip() or "1"
            soc = socs[int(soc_idx) - 1]
            target_records = selected_tag["socs"][soc]
            range_in = (
                input("输入播放范围(秒) (起始: 5 | 范围: 10-30 回车全播): ").strip()
                or "0"
            )

            start, end = 0, 0
            if range_in:
                try:
                    nums = re.findall(r"\d+", range_in)
                    if len(nums) >= 2:
                        start, end = int(nums[0]), int(nums[1])
                    elif len(nums) == 1:
                        start = int(nums[0])
                except ValueError:
                    print("输入错误，开始全量播放...")

            self.player.play(target_records, start, end)
