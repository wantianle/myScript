import logging
import sys
from utils import handles
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

class Recorder:

    def __init__(self, executor):
        self.executor = executor

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
            stdout = self.executor.execute(f"cyber_recorder info {docker_path}")
            return handles.parse_record_info(stdout)
        except Exception as e:
            if "open record file error" in str(e):
                logging.warning(f"Record 文件不存在或无权限访问, 请查看文件路径及权限:")
                print(f"    ls -l {docker_path}")
                print("如果存在权限问题，请确保 Docker 容器对该文件有读取权限:")
                print("    sudo chown -R $USER:$USER /your_data_root && sudo chmod 775 -R /your_data_path")
                raise e
            logging.error(f"解析 Record 元数据失败 [Path: {docker_path}]: {e}")
            sys.exit(1)

    def split(
        self,
        host_in: str,
        host_out: Optional[str] = None,
        start_dt: Optional[datetime] = None,
        end_dt: Optional[datetime] = None,
        blacklist: Optional[List[str]] = None,
    ) -> bool:
        """
        执行 record 切片
        """
        d_in = self.executor.map_path(host_in)
        cmd_parts = ["cyber_recorder split", f"-f {d_in}"]
        if host_out:
            d_out = self.executor.map_path(host_out)
            cmd_parts.append(f"-o {d_out}")
        if start_dt:
            start_str = handles.time_to_str(start_dt)
            cmd_parts.append(f'-b "{start_str}"')
        if end_dt:
            end_str = handles.time_to_str(end_dt)
            cmd_parts.append(f'-e "{end_str}"')
        if blacklist:
            for ch in blacklist:
                cmd_parts.append(f"-k {ch}")
        split_cmd = " ".join(cmd_parts)
        print(split_cmd)
        log_msg = f"Executing Split => "
        log_msg += f"{host_out}" if host_out else f"{host_in}.split"
        logging.info(log_msg)
        CORRUPT_SIGNATURES = [
            "Parse section message failed",
            "read chunk body section fail",
            "not a valid record file",
            "header invalid",
        ]
        try:
            self.executor.execute(split_cmd)
            return True
        except RuntimeError as e:
            err_msg = str(e)
            if any(sig in err_msg for sig in CORRUPT_SIGNATURES):
                logging.warning(f"文件损坏(已跳过): {Path(host_in).name}")
                return False
            logging.error(f"发生未知错误: {err_msg}")
            raise e
