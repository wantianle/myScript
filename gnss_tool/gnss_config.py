"""
GNSS/INS 组合导航 — 纯配置文件
改参数只改这里，不要动执行脚本。
"""

# ═══════════════════════════════════════════════════════════
#  设备连接
# ═══════════════════════════════════════════════════════════
HOST = "192.168.21.10"
PORT = 2003

# ═══════════════════════════════════════════════════════════
#  阶段 1: 周期性日志输出（log netX msg ontime 频率）
#  格式: 每行一个完整命令，可随意增删改
# ═══════════════════════════════════════════════════════════
LOG_PERIODIC = [
    "log net1 HCRAWGNSSPVATB ontime 0.2",
    "log net1 HCINSPVATZCB ontime 0.01",
    "log net1 HCRAWIMUIB ontime 0.01",
    "log net1 gpgga ontime 0.1",
    "log net3 gprmc ontime 1",
]

# ═══════════════════════════════════════════════════════════
#  阶段 2: 事件触发日志输出（log netX msg onnew）
#  格式: 每行一个完整命令，可随意增删改
# ═══════════════════════════════════════════════════════════
LOG_EVENT = [
    "log net1 hclogctclibb onnew",
    "log net1 hclogappb onnew",
    "log net1 hcrawrtcmb onnew",
    "log net1 hcrawrtcmpb onnew",
    "log net1 hcrawodob onnew",
    "log net1 bestgnssposb ontime 0.2",
    "log net1 headingb ontime 0.2",
    "log net1 gpchc ontime 0.1",
]

# ═══════════════════════════════════════════════════════════
#  阶段 3: 杆臂/安装/标定参数
#  格式: {"参数名": "参数值"}，可随意增删改
# ═══════════════════════════════════════════════════════════
CALIB_PARAMS = {
    "INSANGLE":           "0 0 0 5 5 5",
    "HEADINGOFFSET":      "0 0 -90 5.00 5.00 5.00",
    "ANT2BODYOFFSET":     "0.45 -2.706 -1.669 1.00 1.00 1.00",
    "INS2ANTOFFSET":      "-0.456 0.613 1.432 1.00 1.00 1.00",
    "ANT2OUTPOSOFFSET":   "2 0.45 -2.706 -1.949",
    "WHEELTREAD":         "1.3 2.0",
    "BODYTYPE":           "2 0 0",   # 2 0 0 = 低速(<15km/h)标定
}

# ═══════════════════════════════════════════════════════════
#  阶段 4: 收尾命令（改完参数后的操作，可随意增删改）
# ═══════════════════════════════════════════════════════════
FINAL_COMMANDS = [
    "setattitudebase car",
]

# ═══════════════════════════════════════════════════════════
#  saveconfig 时机: 哪些阶段结束后自动保存
# ═══════════════════════════════════════════════════════════
SAVE_AFTER = {
    "LOG_PERIODIC":   True,
    "LOG_EVENT":      True,
    "CALIB_PARAMS":   False,
    "FINAL_COMMANDS": True,
}
