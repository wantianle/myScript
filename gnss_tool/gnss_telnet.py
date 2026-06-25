#!/usr/bin/env python3
"""
组合导航设备 TCP 协议层 (原始 socket，不依赖 telnetlib)
设备: CGI-230 系列
协议: ASCII 文本命令，响应以 $command,[cmd],status 结束
"""

import socket
import re
import time


class NavDevice:
    def __init__(self, host="192.168.21.10", port=2003, timeout=8):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None

    # ─── 连接管理 ───

    def connect(self):
        self.sock = socket.create_connection(
            (self.host, self.port), timeout=self.timeout)
        self.sock.settimeout(self.timeout)
        # 吃掉连接时的 banner（"Trying... Connected... Escape..."）
        time.sleep(0.3)
        self._drain()
        return self

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    def _drain(self):
        """排空 socket 缓冲区"""
        self.sock.setblocking(False)
        try:
            while True:
                chunk = self.sock.recv(4096)
                if not chunk:
                    break
        except Exception:
            pass
        self.sock.setblocking(True)

    # ─── 接收辅助 ───

    def _recv_until(self, marker, timeout=None):
        """
        读数据直到遇到 marker 字符串，返回 (包含 marker 的) 全部数据。
        超时返回已读到的数据（可能为空）。
        """
        if timeout is None:
            timeout = self.timeout
        deadline = time.time() + timeout
        buf = b""
        while time.time() < deadline:
            try:
                remain = deadline - time.time()
                if remain <= 0:
                    break
                self.sock.settimeout(max(0.1, remain))
                chunk = self.sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
                if marker in buf:
                    return buf
            except socket.timeout:
                break
            except Exception:
                break
        return buf

    # ─── 核心命令发送 ───

    def cmd(self, command):
        """发送命令，返回 (ok?, 响应全文含状态行)"""
        if not self.sock:
            raise ConnectionError("未连接，先调用 connect()")

        # 清上一次残留
        self._drain()

        try:
            self.sock.sendall(command.encode() + b"\r\n")
        except (BrokenPipeError, ConnectionResetError, OSError):
            return False, "(连接已断开)"

        # 读响应，直到出现 $command, 标记
        buf = self._recv_until(b"$command,", self.timeout)
        if b"$command," not in buf:
            # 可能响应慢，再等一下
            time.sleep(0.2)
            buf += self._recv_until(b"$command,", 2)

        if b"$command," not in buf:
            return False, "(超时/无响应)"

        # 读状态行剩余部分 (直到换行)
        more = self._recv_until(b"\n", 2)
        buf += more

        # "log xxx once" 类命令：数据在状态行之后，再追读一行
        time.sleep(0.05)
        trailing = self._recv_until(b"\n", 0.5)
        if trailing:
            buf += trailing

        full = buf.decode(errors="ignore")
        ok = "$command," in full and "ok" in full
        return ok, full.strip()

    def cmd_data(self, command):
        """同 cmd()，但去掉状态行，只返回数据部分"""
        ok, full = self.cmd(command)
        lines = full.split("\n")
        data_lines = [l for l in lines if not l.startswith("$command,")]
        return ok, "\n".join(data_lines).strip()

    # ─── 读取方法 ───

    def read_interface(self):
        return self.cmd_data("interface")

    def read_version(self):
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

    def read_config(self):
        ok, data = self.cmd_data("getting gilccfg")
        sections = {}
        current_section = None
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
            if ":" in line and current_section:
                key, val = line.split(":", 1)
                key = key.strip()
                val = val.strip()
                sections[current_section][key] = val
            elif current_section and sections.get(current_section):
                last_key = list(sections[current_section].keys())[-1]
                sections[current_section][last_key] += " " + line.strip()
        return {"raw": data, "sections": sections}

    def read_loglist(self):
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
                if len(parts) >= 3:
                    logs.append({"name": parts[0], "port": parts[1], "rate": parts[2]})
        return logs

    def read_gpchc_once(self):
        ok, data = self.cmd_data("log gpchc once")
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
        result = {"raw": data, "ok": ok}
        for line in data.split("\n"):
            line = line.strip()
            if line.startswith("$GPCHC,"):
                values = line.split(",")
                for i, f in enumerate(fields):
                    if i + 1 < len(values):
                        result[f] = values[i + 1]
                break
        return result

    def read_gpchcx_once(self):
        return self.cmd_data("log gpchcx once")

    def check_gpchc_status(self):
        ok, data = self.cmd_data("log gpchc once")
        result = {"ok": ok, "raw": data, "status_hex": None, "rtk_fixed": False, "message": ""}

        for line in data.split("\n"):
            line = line.strip()
            if not line.startswith("$GPCHC,"):
                continue
            fields = line.split(",")
            if fields and "*" in fields[-1]:
                fields = fields[:-1]
            if len(fields) >= 3:
                status_str = fields[-2].strip()
                try:
                    result["status_hex"] = int(status_str, 16)
                except ValueError:
                    result["status_hex"] = None
                    result["message"] = "无法解析 Status 字段: " + status_str
                    return result

                sv = result["status_hex"]
                if sv == 0x42:
                    result["rtk_fixed"] = True
                    result["message"] = "RTK 固定解 + 组合导航模式 — 正常"
                elif sv == 0x61:
                    result["message"] = "⚠ 单点不定向 + 卫导模式 — 无 RTK 配置输出或差分账号错误"
                else:
                    high = (sv >> 4) & 0xF
                    low = sv & 0xF
                    sys_map = {0: "初始化", 1: "卫导模式", 2: "组合导航", 3: "纯惯导"}
                    sat_map = {0: "不定位不定向", 1: "单点定位定向", 2: "伪距差分", 3: "组合推算",
                               4: "RTK 稳定解", 5: "RTK 浮点解", 6: "单点不定向",
                               7: "伪距差分不定向", 8: "RTK 稳定不定向", 9: "RTK 浮点不定向"}
                    sys_name = sys_map.get(low, "未知(" + str(low) + ")")
                    sat_name = sat_map.get(high, "未知(" + str(high) + ")")
                    result["message"] = "0x{:02X}: {} + {}".format(sv, sat_name, sys_name)
            break

        return result

    def save_config(self):
        ok, _ = self.cmd("saveconfig")
        return ok
