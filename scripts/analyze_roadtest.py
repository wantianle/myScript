#!/usr/bin/env python3

import sys
import time
from collections import defaultdict

from cyber_python.cyber_py3 import cyber
from cyber_python.cyber_py3 import record
from modules.message.chassis_pb2 import Chassis
from modules.message.chassis_signal_pb2 import InstrumentSignal


def analyze_record(file_path):
    """
    分析record文件，统计路测指标
    """
    freader = record.RecordReader(file_path)
    channels = freader.get_channellist()

    # 初始化统计变量
    total_mileage = 0.0
    autonomous_mileage = 0.0
    takeover_count = 0
    takeover_mileages = []  # 记录每次接管时的里程
    prev_mileage = 0.0
    prev_state = None

    # 读取所有消息
    for channel in channels:
        if channel == "/apollo/canbus/chassis":
            msg_iter = freader.read_messages(channel)
            for msg in msg_iter:
                chassis = Chassis()
                chassis.ParseFromString(msg[1])

                current_mileage = chassis.odometer_m / 1000.0  # 转换为km

                # 计算总里程增量
                if prev_mileage > 0:
                    mileage_delta = current_mileage - prev_mileage
                    total_mileage += mileage_delta

                    # 如果在自动驾驶状态，累加自动驾驶里程
                    if prev_state == 3:  # RUN状态
                        autonomous_mileage += mileage_delta

                prev_mileage = current_mileage

                # 获取当前状态
                if chassis.HasField("instrument_signal"):
                    current_state = chassis.instrument_signal.state
                    # 检测接管事件
                    if prev_state == 3 and current_state in [
                        4,
                        7,
                    ]:  # 从RUN到MANUAL或IMMEDIATE_TAKEOVER
                        takeover_count += 1
                        takeover_mileages.append(current_mileage)  # 记录接管时的里程
                    prev_state = current_state

    # 计算MPI（平均接管里程）
    mpi_avg = total_mileage / (takeover_count + 1) if total_mileage > 0 else 0.0

    # 输出结果
    print("=== 路测统计结果 ===")
    print(f"总里程: {total_mileage:.2f} km")
    print(f"自动驾驶里程: {autonomous_mileage:.2f} km")
    print(f"接管次数: {takeover_count}")
    print(f"MPI (平均接管里程): {mpi_avg:.2f} km")
    print(
        f"自动驾驶占比: {autonomous_mileage / total_mileage * 100:.1f}%"
        if total_mileage > 0
        else "N/A"
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python analyze_roadtest.py record_file.record")
        sys.exit(1)

    cyber.init()
    analyze_record(sys.argv[1])
    cyber.shutdown()
