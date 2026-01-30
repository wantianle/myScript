import logging
from utils import parser
from pathlib import Path
from typing import Dict, List, Optional, Any

from interface import ui


class Recorder:
    def __init__(self, session):
        self.session = session

    def get_info(self, docker_path: str) -> Dict[str, Any]:
        """
        获取 record 的时间、时长、排序后的频道列表
        """
        try:
            stdout = self.session.executor.execute(f"cyber_recorder info {docker_path}")
            return parser.parse_record_info(stdout)
        except Exception as e:
            ui.print_status(f"{docker_path} 异常，解析元数据失败", "ERROR")
            raise e

    def split(
        self,
        host_in: str,
        host_out: Optional[str],
        start_dt: Optional[str],
        end_dt: Optional[str],
        blacklist: Optional[List[str]] = None,
    ):
        """
        执行 record 切片
        """
        logging.info(f"[RECORDER_SLICE] File: {Path(host_in).name}")
        logging.info(f"  Range: {start_dt} -> {end_dt}")

        cmd_parts = ["cyber_recorder split", f"-f {host_in}"]
        cmd_parts.append(f'-o "{host_out}"')
        if start_dt:
            cmd_parts.append(f'-b "{parser.time_to_str(start_dt)}"')
        if end_dt:
            cmd_parts.append(f'-e "{parser.time_to_str(end_dt)}"')
        if blacklist:
            for ch in blacklist:
                cmd_parts.append(f"-k {ch}")
        split_cmd = " ".join(cmd_parts)

        try:
            self.session.executor.execute(split_cmd)
        except Exception as e:
            ui.print_status(f"文件损坏(已跳过): {host_in}", "WARN")
            logging.debug(f"{host_in} 文件损坏: {e}")
