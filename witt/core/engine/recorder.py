import logging
from utils import handles
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

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
            return handles.parse_record_info(stdout)
        except Exception as e:
            logging.error(f"解析 Record 元数据失败 [Path: {docker_path}]: {e}")
            raise e

    def split_async(
        self,
        host_in: str,
        host_out: str,
        start_dt: str,
        end_dt: str,
        blacklist: List[str],
    ) -> bool:
        """
        执行 record 切片
        """
        d_in = self.session.executor.map_path(host_in)
        d_out = self.session.executor.map_path(host_out)
        cmd_parts = ["cyber_recorder split", f"-f {d_in}", f"-o {d_out}"]
        if start_dt: cmd_parts.append(f'-b "{handles.time_to_str(start_dt)}"')
        if end_dt: cmd_parts.append(f'-e "{handles.time_to_str(end_dt)}"')
        if blacklist:
            for ch in blacklist: cmd_parts.append(f"-k {ch}")
        split_cmd = " ".join(cmd_parts)
        return self.session.executor.popen(split_cmd)

    def split(
        self,
        host_in: str,
        host_out: Optional[str],
        start_dt: Optional[str],
        end_dt: Optional[str],
        blacklist: Optional[List[str]]=None,
    ) -> bool:
        """
        执行 record 切片
        """
        logging.info(f"[SLICE_START] File: {Path(host_in).name}")
        logging.info(f"    Range: {start_dt} -> {end_dt}")
        if blacklist:
            logging.info(f"    Blacklist: {','.join(blacklist)}")

        cmd_parts = ["cyber_recorder split", f"-f {host_in}"]
        cmd_parts.append(f'-o "{handles.time_to_str(host_out)}"')
        if start_dt: cmd_parts.append(f'-b "{handles.time_to_str(start_dt)}"')
        if end_dt: cmd_parts.append(f'-e "{handles.time_to_str(end_dt)}"')
        if blacklist:
            for ch in blacklist: cmd_parts.append(f"-k {ch}")
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
                logging.warning(f"文件损坏(已跳过): {Path(host_in).name}")
                return False
            logging.error(f"发生未知错误: {err_msg}")
            raise e
