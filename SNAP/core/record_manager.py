import re
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any


class RecordManager:
    RE_TIME = re.compile(r"(\d{4}[-\s]\d{2}[-\s]\d{2}[-\s]\d{2}:\d{2}:\d{2})")
    RE_CHANNEL = re.compile(r"(\/mdrive\/[\/\w]+)\s+(\d+)\s+messages")

    def __init__(self, docker_executor):
        self.executor = docker_executor

    def get_info(self, docker_path: str) -> Dict[str, Any]:
        """
        获取 record 的时间、时长、排序后的频道列表
        """
        try:
            stdout = self.executor.execute(f"cyber_recorder info {docker_path}")
            begin_time = (
                self._parse_cyber_time(m.group(1))
                if (m := re.search(rf"begin_time:\s+{self.RE_TIME.pattern}", stdout))
                else None
            )
            end_time = (
                self._parse_cyber_time(m.group(1))
                if (m := re.search(rf"end_time:\s+{self.RE_TIME.pattern}", stdout))
                else None
            )
            return {
                "begin": begin_time,
                "end": end_time,
                "channels": self._extract_channels(stdout),
            }
        except Exception as e:
            logging.error(f"解析 Record 元数据失败 [Path: {docker_path}]: {e}")
            return {"begin": None, "end": None, "channels": []}

    def _extract_channels(self, stdout: str) -> List[Dict[str, Any]]:
        """解析并排序频道列表"""
        matches = self.RE_CHANNEL.findall(stdout)
        raw_channels = [{"name": name, "count": int(count)} for name, count in matches]
        return sorted(raw_channels, key=lambda x: x["name"])

    def _parse_cyber_time(self, t_str: str) -> Optional[datetime]:
        """
        统一解析 Cyber 时间字符串为 target_date 对象
        处理情况：2025-12-27-16:28:10 -> 2025-12-27 16:28:10
        """
        if not t_str:
            return None
        clean_t = t_str
        if len(t_str) > 10 and t_str[10] == "-":
            clean_t = f"{t_str[:10]} {t_str[11:]}"

        try:
            return datetime.strptime(clean_t, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            logging.error(f"无法识别的时间格式: {t_str}")
            return None

    def _format_for_cyber(self, dt: Any) -> str:
        """转回 Cyber 要求的字符串"""
        if isinstance(dt, datetime):
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        return str(dt)

    def split(
        self,
        host_in: str,
        host_out: str,
        start_dt: Any,
        end_dt: Any,
        blacklist: Optional[List[str]] = None,
    ):
        """
        执行 record 切片
        """
        d_in = self.executor.to_docker_path(host_in)
        d_out = self.executor.to_docker_path(host_out)
        start_str = self._format_for_cyber(start_dt)
        end_str = self._format_for_cyber(end_dt)
        cmd_parts = [
            "cyber_recorder split",
            f"-f {d_in}",
            f"-o {d_out}",
            f'-b "{start_str}"',
            f'-e "{end_str}"',
        ]
        # 动态添加黑名单频道
        if blacklist:
            for ch in blacklist:
                cmd_parts.append(f"-k {ch}")

        cmd = " ".join(cmd_parts)
        logging.info(
            f"Executing Split: [{start_str}] -> [{end_str}] | Output: {host_out}"
        )
        return self.executor.execute(cmd)
