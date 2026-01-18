import logging
from utils import parser
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from interface import ui

class Recorder:

    def __init__(self, session):
        self.session = session

    def get_info(
        self, docker_path: str, fast_meta: Optional[dict] = None
    ) -> Dict[str, Any]:
        """
        获取 record 的时间、时长、排序后的频道列表
        """
        if fast_meta:
            return {
                "begin": datetime.fromisoformat(fast_meta["tag_info"]["abs_start"]),
                "end": datetime.fromisoformat(fast_meta["tag_info"]["abs_end"]),
                "duration": fast_meta["tag_info"]["offset_bf"]
                + fast_meta["tag_info"]["offset_af"],
                "channels": [],
            }
        try:
            stdout = self.session.executor.execute(f"cyber_recorder info {docker_path}")
            return parser.parse_record_info(stdout)
        except Exception as e:
            ui.print_status(f"解析 Record 元数据失败...", "ERROR")
            raise e

    def split(
        self,
        host_in: str,
        host_out: Optional[str],
        start_dt: Optional[str],
        end_dt: Optional[str],
        blacklist: Optional[List[str]] = None,
    ) -> bool:
        """
        执行 record 切片
        """
        logging.info(f"[SLICE_START] File: {Path(host_in).name}")
        logging.info(f"    Range: {start_dt} -> {end_dt}")
        if blacklist:
            logging.info(f"    Blacklist: {','.join(blacklist)}")

        cmd_parts = ["cyber_recorder split", f"-f {host_in}"]
        cmd_parts.append(f'-o "{parser.time_to_str(host_out)}"')
        if start_dt:
            cmd_parts.append(f'-b "{parser.time_to_str(start_dt)}"')
        if end_dt:
            cmd_parts.append(f'-e "{parser.time_to_str(end_dt)}"')
        if blacklist:
            for ch in blacklist:
                cmd_parts.append(f"-k {ch}")
        split_cmd = " ".join(cmd_parts)
        CORRUPT_SIGNATURES = [
            "Parse section message failed",
            "read chunk body section fail",
            "not a valid record file",
            "header invalid",
        ]
        try:
            self.session.executor.execute(split_cmd)
            return True
        except RuntimeError as e:
            err_msg = str(e)
            if any(sig in err_msg for sig in CORRUPT_SIGNATURES):
                ui.print_status(f"文件损坏(已跳过): {Path(host_in).name}", "WARN")
                return False
            raise e
