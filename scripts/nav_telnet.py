#!/usr/bin/env python3
"""
组合导航设备 Telnet 自动化工具
设备: 192.168.21.10:2003
协议: 纯文本命令，响应以 $command,[cmd],status 结束
"""

import telnetlib
import re
import time
import sys

HOST = "192.168.21.10"
PORT = 2003
TIMEOUT = 8


class NavDevice:
    def __init__(self, host=HOST, port=PORT, timeout=TIMEOUT):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.tn = None

    def connect(self):
        """建立 Telnet 连接"""
        self.tn = telnetlib.Telnet(self.host, self.port, timeout=self.timeout)
        # 吃掉连接建立时的 banner（"Trying... Connected... Escape..." 等）
        # 设备连上不会主动发东西，等一小段时间让 banner 走完
        time.sleep(0.5)
        # 清空残留
        try:
            self.tn.read_very_eager()
        except Exception:
            pass
        return self

    def close(self):
        if self.tn:
            self.tn.close()

    def cmd(self, command: str) -> tuple[bool, str]:
        """
        发送命令，返回 (成功, 响应全文)
        响应包含数据部分和 $command,[cmd],status 收尾行
        """
        if not self.tn:
            raise ConnectionError("未连接，先调用 connect()")

        self.tn.write(command.encode() + b"\n")

        # 读取直到 $command, 标记（包含所有数据输出）
        raw = self.tn.read_until(b"$command,", timeout=self.timeout)
        # 再读状态行剩余部分
        status_line = self.tn.read_until(b"\n", timeout=self.timeout)
        full = (raw + status_line).decode(errors="ignore")

        success = "ok" in status_line.decode(errors="ignore")
        return success, full.strip()

    def cmd_data(self, command: str) -> tuple[bool, str]:
        """
        发送命令，返回 (成功, 纯数据部分)
        去掉了 $command,... 状态行
        """
        ok, full = self.cmd(command)
        # 去掉最后一行的状态标记
        lines = full.split("\n")
        # 找到最后一行 $command,... 并移除
        data_lines = [l for l in lines if not l.startswith("$command,")]
        return ok, "\n".join(data_lines).strip()


# ─── 业务查询方法 ───

    def get_version(self) -> dict:
        """获取版本信息"""
        ok, data = self.cmd_data("getting version")
        info = {"raw": data}
        for line in data.split("\n"):
            line = line.strip()
            if line.startswith("[COM7]VER:"):
                info["version"] = line.split(":", 1)[1]
            elif line.startswith("AUTOR:"):
                info["author"] = line.split(":", 1)[1]
            elif line.startswith("INFO:"):
                info["info"] = line.split(":", 1)[1]
            elif line.startswith("GPR:"):
                info["gpr"] = line.split(":", 1)[1]
        return info

    def get_config(self) -> dict:
        """获取 gilccfg 配置，解析为字典。返回 {'raw': ..., 'sections': {...}}"""
        ok, data = self.cmd_data("getting gilccfg")
        sections: dict[str, dict] = {}
        current_section: str | None = None
        for line in data.split("\n"):
            line = line.strip()
            if not line:
                continue
            m = re.match(r"\[(\w+)\]", line)
            if m:
                section = m.group(1)
                sections[section] = {}
                current_section = section
                continue
            # 键值对
            if ":" in line and current_section:
                key, val = line.split(":", 1)
                key = key.strip()
                val = val.strip()
                sections[current_section][key] = val
            # 多行值的延续
            elif current_section and sections.get(current_section):
                last_key = list(sections[current_section].keys())[-1]
                sections[current_section][last_key] += " " + line.strip()
        return {"raw": data, "sections": sections}

    def get_gpchc(self) -> dict:
        """获取当前 GNSS/IMU 组合数据 ($GPCHC)"""
        ok, data = self.cmd_data("log gpchc")
        fields = [
            "msg_id", "week", "tow",
            "heading", "pitch", "roll",
            "gyro_x", "gyro_y", "gyro_z",
            "accel_x", "accel_y", "accel_z",
            "lat", "lon", "alt",
            "ve", "vn", "vu",
            "baseline", "nsv1", "nsv2",
            "status", "age", "cs",
        ]
        result = {"raw": data}
        for line in data.split("\n"):
            line = line.strip()
            if line.startswith("$GPCHC,"):
                values = line.split(",")
                for i, field in enumerate(fields):
                    if i + 1 < len(values):
                        result[field] = values[i + 1]
                break
        return result

    def get_loglist(self) -> list[dict]:
        """获取日志输出列表"""
        ok, data = self.cmd_data("log loglist")
        logs = []
        header_done = False
        for line in data.split("\n"):
            line = line.strip()
            if line.startswith("#LOGLIST,"):
                header_done = True
                continue
            if header_done and line.startswith("<"):
                parts = line[1:].strip().split(None, 2)
                if len(parts) == 3:
                    logs.append({
                        "name": parts[0],
                        "port": parts[1],
                        "rate": parts[2],
                    })
        return logs

    def set_config(self, key: str, value: str) -> bool:
        """设置配置项（根据设备命令格式调整）"""
        ok, _ = self.cmd(f"set {key} {value}")
        return ok

    def save_config(self) -> bool:
        """保存配置到设备"""
        ok, _ = self.cmd("saveconfig")
        return ok


# ─── 命令行入口 ───

def main():
    dev = NavDevice()
    print(f"连接 {HOST}:{PORT} ...")
    dev.connect()
    print("已连接\n")

    try:
        # ── 示例：读取版本 ──
        print("=== 版本信息 ===")
        ver = dev.get_version()
        for k, v in ver.items():
            if k != "raw":
                print(f"  {k}: {v}")

        # ── 示例：读取配置 ──
        print("\n=== 当前配置 ===")
        cfg = dev.get_config()
        for section, items in cfg["sections"].items():
            print(f"  [{section}]")
            for k, v in items.items():
                print(f"    {k}: {v}")

        # ── 示例：读取实时数据 ──
        print("\n=== 实时 GNSS/IMU ===")
        gpchc = dev.get_gpchc()
        for k, v in gpchc.items():
            if k != "raw":
                print(f"  {k}: {v}")

        # ── 示例：日志列表 ──
        print("\n=== 日志输出列表 ===")
        logs = dev.get_loglist()
        for entry in logs:
            print(f"  {entry['name']:20s} {entry['port']:6s} {entry['rate']}")

        # ── 示例：修改配置并保存 ──
        # 取消注释来实际修改：
        # dev.set_config("HEADINGOFFSET", "0.00 0.00 -90.00 5.00 5.00 5.00")
        # dev.save_config()
        # print("\n配置已保存")

    finally:
        dev.close()
        print("\n连接已关闭")


if __name__ == "__main__":
    main()
