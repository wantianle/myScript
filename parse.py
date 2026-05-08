#!/usr/bin/env python3

###############################################################################
# Copyright 2023 The Minieye L4 Team. All Rights Reserved.
###############################################################################

'''
解析系统性能日志文件，生成可视化图表
包括: CPU性能曲线、各CPU上的进程开销情况、各进程CPU开销曲线
'''

import argparse
import os
import sys
import glob
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
from collections import defaultdict
import numpy as np


def get_process_basename(cmdline):
    """从命令行获取进程basename（最后一个'/'后的名字）"""
    if not cmdline:
        return None
    cmdline = cmdline.strip()
    # 去掉引号
    cmdline = cmdline.strip('"')
    # 查找最后一个空格分隔的部分（通常是程序名）
    parts = cmdline.split()
    if not parts:
        return None
    # 获取第一个参数（通常是程序路径）
    program_path = parts[0]
    # 提取basename（最后一个'/'后的部分）
    if '/' in program_path:
        return program_path.rsplit('/', 1)[-1]
    return program_path


def get_process_display_name(cmdline, pid):
    """获取进程显示名称：优先使用basename，否则使用PID"""
    basename = get_process_basename(cmdline)
    if basename:
        return basename
    return f'PID_{pid}'


class PerformanceData:
    """存储性能数据的类"""

    def __init__(self):
        # CPU数据: {cpu_id: [(timestamp, percent), ...]}
        self.cpu_data = defaultdict(list)

        # 进程数据: {pid: [(timestamp, cpu_percent, cpu_num), ...]}
        self.process_data = defaultdict(list)

        # 进程命令行映射: {pid: cmdline}
        self.process_cmdlines = {}

        # 按CPU分组的进程数据: {cpu_id: {pid: [(timestamp, cpu_percent), ...]}}
        self.cpu_process_data = defaultdict(lambda: defaultdict(list))

        # 时间范围
        self.start_time = None
        self.end_time = None


def _parse_csv_with_quotes(line):
    """解析包含引号的CSV行"""
    parts = []
    current = []
    in_quotes = False

    for char in line:
        if char == '"':
            in_quotes = not in_quotes
        elif char == ',' and not in_quotes:
            parts.append(''.join(current))
            current = []
        else:
            current.append(char)

    if current:
        parts.append(''.join(current))

    return parts


def parse_log_file(log_file):
    """解析性能日志文件"""
    data = PerformanceData()

    print(f"Parsing log file: {log_file}")

    # 从系统头部获取CPU数量
    num_cpus = 12  # 默认值

    with open(log_file, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            # 检查是否是系统头部，获取CPU数量
            if line.startswith('sh,'):
                parts = line.split(',')
                # 统计percent-*字段的数量
                for i, col in enumerate(parts[2:], start=0):
                    if col.startswith('percent-'):
                        num_cpus = i + 1
                    else:
                        break
                print(f"Detected {num_cpus} CPUs from header")
                continue

            parts = _parse_csv_with_quotes(line)
            if len(parts) < 2:
                continue

            record_type = parts[0]

            if record_type == 'sd':
                # 系统数据: sd,timestamp,percent-0,...,percent-11,freq-0,...
                # 只有前12个数值是CPU使用率
                if len(parts) < 2 + num_cpus:
                    continue
                try:
                    timestamp = float(parts[1])
                    if data.start_time is None:
                        data.start_time = timestamp
                    data.end_time = timestamp

                    # 解析CPU使用率，只取前num_cpus个
                    for cpu_idx in range(num_cpus):
                        percent = float(parts[2 + cpu_idx])
                        data.cpu_data[cpu_idx].append((timestamp, percent))

                except (ValueError, IndexError) as e:
                    print(f"Warning: Failed to parse system data line: {e}")
                    continue

            elif record_type == 'th':
                # 任务头部，跳过
                continue

            elif record_type == 'td':
                # 任务数据: td,timestamp,pid,cmdline,status,mem-rss,mem-vms,mem-shared,cpu,cpu-user,cpu-system,ctx-switch-voluntary,ctx-switch-involuntary,cpu-num
                if len(parts) < 14:
                    continue
                try:
                    timestamp = float(parts[1])
                    pid = int(parts[2])
                    cmdline = parts[3]
                    # status = parts[4]
                    # mem_rss = int(parts[5])
                    cpu_percent = float(parts[8])
                    # cpu_user = float(parts[9])
                    # cpu_system = float(parts[10])
                    # ctx_voluntary = int(parts[11])
                    # ctx_involuntary = int(parts[12])
                    cpu_num = int(parts[13]) if len(parts) > 13 else 0

                    # 保存进程命令行（去掉引号）
                    if cmdline:
                        cmdline = cmdline.strip('"')
                        if pid not in data.process_cmdlines:
                            data.process_cmdlines[pid] = cmdline

                    # 保存进程数据
                    data.process_data[pid].append((timestamp, cpu_percent, cpu_num))

                    # 按CPU分组保存进程数据
                    data.cpu_process_data[cpu_num][pid].append((timestamp, cpu_percent))

                except (ValueError, IndexError) as e:
                    print(f"Warning: Failed to parse task data line: {e}")
                    continue

    print(f"Parsed {len(data.cpu_data)} CPUs, {len(data.process_data)} processes")
    return data


def plot_cpu_performance(data, output_dir):
    """为每个CPU单独绘制性能曲线图"""
    print("Generating CPU performance plots...")

    cpu_dir = os.path.join(output_dir, 'cpu_performance')
    os.makedirs(cpu_dir, exist_ok=True)

    # 为每个CPU生成单独的图表
    for cpu_id in sorted(data.cpu_data.keys()):
        timestamps, percents = zip(*data.cpu_data[cpu_id])

        # 转换时间戳为可读时间
        dates = [datetime.fromtimestamp(ts) for ts in timestamps]

        plt.figure(figsize=(12, 4))
        plt.plot(dates, percents, linewidth=1, color='steelblue')
        plt.fill_between(dates, percents, alpha=0.3, color='steelblue')

        plt.title(f'CPU {cpu_id} Performance')
        plt.xlabel('Time')
        plt.ylabel('CPU Usage (%)')
        plt.ylim(0, 105)
        plt.grid(True, alpha=0.3)

        # 格式化x轴时间显示
        ax = plt.gca()
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        plt.xticks(rotation=45)

        plt.tight_layout()
        output_file = os.path.join(cpu_dir, f'cpu_{cpu_id}.png')
        plt.savefig(output_file, dpi=150)
        plt.close()

    # 生成所有CPU的综合图表
    plt.figure(figsize=(14, 8))
    for cpu_id in sorted(data.cpu_data.keys()):
        timestamps, percents = zip(*data.cpu_data[cpu_id])
        dates = [datetime.fromtimestamp(ts) for ts in timestamps]
        plt.plot(dates, percents, label=f'CPU {cpu_id}', linewidth=1)

    plt.title('All CPUs Performance')
    plt.xlabel('Time')
    plt.ylabel('CPU Usage (%)')
    plt.ylim(0, 105)
    plt.legend(loc='upper left', bbox_to_anchor=(1, 1), ncol=2)
    plt.grid(True, alpha=0.3)

    ax = plt.gca()
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
    plt.xticks(rotation=45)

    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, 'all_cpus.png'), dpi=150)
    plt.close()

    print(f"  CPU plots saved to: {cpu_dir}")


def plot_cpu_with_processes(data, output_dir):
    """绘制每个CPU及其上运行的进程开销情况"""
    print("Generating CPU with process overhead plots...")

    cpu_process_dir = os.path.join(output_dir, 'cpu_with_processes')
    os.makedirs(cpu_process_dir, exist_ok=True)

    # 对每个CPU生成图表
    for cpu_id in sorted(data.cpu_process_data.keys()):
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8),
                                        height_ratios=[1, 2],
                                        sharex=True)

        timestamps = None
        cpu_percents = None

        # 上方子图: CPU总使用率
        if cpu_id in data.cpu_data:
            timestamps, cpu_percents = zip(*data.cpu_data[cpu_id])
            dates = [datetime.fromtimestamp(ts) for ts in timestamps]
            ax1.plot(dates, cpu_percents, linewidth=1.5, color='steelblue', label='Total CPU')
            ax1.fill_between(dates, cpu_percents, alpha=0.3, color='steelblue')
            ax1.set_ylabel('CPU Usage (%)')
            ax1.set_ylim(0, 105)
            ax1.grid(True, alpha=0.3)
            ax1.legend(loc='upper left')

        # 下方子图: 各进程在该CPU上的开销
        # 获取在该CPU上运行最多的前10个进程
        process_totals = {}
        for pid, samples in data.cpu_process_data[cpu_id].items():
            total = sum(cpu for _, cpu in samples)
            process_totals[pid] = total

        top_pids = sorted(process_totals.items(), key=lambda x: x[1], reverse=True)[:10]

        # 为每个进程绘制曲线
        colors = plt.cm.tab10(np.linspace(0, 1, len(top_pids)))
        for idx, (pid, _) in enumerate(top_pids):
            if pid in data.cpu_process_data[cpu_id]:
                proc_timestamps, proc_percents = zip(*data.cpu_process_data[cpu_id][pid])
                proc_dates = [datetime.fromtimestamp(ts) for ts in proc_timestamps]

                cmdline = data.process_cmdlines.get(pid, '')
                name = get_process_display_name(cmdline, pid)

                ax2.plot(proc_dates, proc_percents, label=name, linewidth=1, color=colors[idx])

        ax2.set_xlabel('Time')
        ax2.set_ylabel('Process CPU Usage (%)')
        ax2.set_ylim(0, 105)
        ax2.legend(loc='upper left', bbox_to_anchor=(1, 1), fontsize=8)
        ax2.grid(True, alpha=0.3)

        # 格式化x轴
        ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        plt.xticks(rotation=45)

        plt.suptitle(f'CPU {cpu_id} with Process Overhead', fontsize=14, y=0.995)
        plt.tight_layout()

        output_file = os.path.join(cpu_process_dir, f'cpu_{cpu_id}_processes.png')
        plt.savefig(output_file, dpi=150, bbox_inches='tight')
        plt.close()

    print(f"  CPU with process plots saved to: {cpu_process_dir}")


def plot_process_performance(data, output_dir, top_n=20):
    """为每个进程单独绘制完整的CPU开销曲线图"""
    print("Generating process performance plots...")

    process_dir = os.path.join(output_dir, 'process_performance')
    os.makedirs(process_dir, exist_ok=True)

    # 计算每个进程的总CPU使用量
    process_totals = {}
    for pid, samples in data.process_data.items():
        total = sum(cpu for _, cpu, _ in samples)
        process_totals[pid] = total

    # 按总使用量排序，只取前N个进程
    top_pids = sorted(process_totals.items(), key=lambda x: x[1], reverse=True)[:top_n]

    for idx, (pid, _) in enumerate(top_pids):
        if pid not in data.process_data:
            continue

        samples = data.process_data[pid]
        timestamps = [s[0] for s in samples]
        cpu_percents = [s[1] for s in samples]
        cpu_nums = [s[2] for s in samples]

        dates = [datetime.fromtimestamp(ts) for ts in timestamps]

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 6), sharex=True)

        # 上方子图: CPU使用率
        ax1.plot(dates, cpu_percents, linewidth=1, color='coral')
        ax1.fill_between(dates, cpu_percents, alpha=0.3, color='coral')
        ax1.set_ylabel('CPU Usage (%)')
        ax1.set_ylim(0, max(max(cpu_percents) * 1.1, 100))
        ax1.grid(True, alpha=0.3)
        ax1.set_title('CPU Usage', fontsize=10)

        # 下方子图: 运行在哪个CPU上
        ax2.scatter(dates, cpu_nums, s=10, alpha=0.5, color='teal')
        ax2.set_ylabel('CPU Core')
        ax2.set_xlabel('Time')
        ax2.set_ylim(-1, max(max(cpu_nums) + 1, 12))
        ax2.grid(True, alpha=0.3)
        ax2.set_title('CPU Core Assignment', fontsize=10)

        # 格式化x轴
        ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        plt.xticks(rotation=45)

        cmdline = data.process_cmdlines.get(pid, '')
        display_name = get_process_display_name(cmdline, pid)
        plt.suptitle(f'{display_name} (PID: {pid})', fontsize=12)
        plt.tight_layout()

        # 使用进程basename作为文件名
        basename = get_process_basename(cmdline)
        if basename:
            safe_name = basename.replace(' ', '_')[:50]
        else:
            safe_name = f'PID_{pid}'
        output_file = os.path.join(process_dir, f'process_{pid}_{safe_name}.png')
        plt.savefig(output_file, dpi=150, bbox_inches='tight')
        plt.close()

    print(f"  Process plots saved to: {process_dir}")


def generate_summary_report(data, output_dir):
    """生成汇总报告"""
    print("Generating summary report...")

    report_file = os.path.join(output_dir, 'summary_report.txt')

    with open(report_file, 'w') as f:
        f.write("=" * 80 + "\n")
        f.write("System Performance Analysis Report\n")
        f.write("=" * 80 + "\n\n")

        if data.start_time and data.end_time:
            duration = data.end_time - data.start_time
            f.write(f"Time Range:\n")
            f.write(f"  Start: {datetime.fromtimestamp(data.start_time)}\n")
            f.write(f"  End:   {datetime.fromtimestamp(data.end_time)}\n")
            f.write(f"  Duration: {duration:.2f} seconds\n\n")

        f.write(f"CPU Count: {len(data.cpu_data)}\n")
        f.write(f"Process Count: {len(data.process_data)}\n\n")

        # CPU使用率统计
        f.write("-" * 80 + "\n")
        f.write("CPU Usage Statistics:\n")
        f.write("-" * 80 + "\n")
        for cpu_id in sorted(data.cpu_data.keys()):
            percents = [p for _, p in data.cpu_data[cpu_id]]
            if percents:
                f.write(f"  CPU {cpu_id:2d}: Avg: {np.mean(percents):5.1f}%, "
                       f"Max: {np.max(percents):5.1f}%, "
                       f"Min: {np.min(percents):5.1f}%\n")

        # 进程CPU使用率统计
        f.write("\n" + "-" * 80 + "\n")
        f.write("Top 20 Processes by Total CPU Usage:\n")
        f.write("-" * 80 + "\n")

        process_totals = {}
        for pid, samples in data.process_data.items():
            total = sum(cpu for _, cpu, _ in samples)
            process_totals[pid] = total

        top_pids = sorted(process_totals.items(), key=lambda x: x[1], reverse=True)[:20]

        for idx, (pid, total) in enumerate(top_pids):
            samples = data.process_data[pid]
            percents = [cpu for _, cpu, _ in samples]
            cmdline = data.process_cmdlines.get(pid, 'Unknown')
            display_name = get_process_display_name(cmdline, pid)
            f.write(f"  {idx+1:2d}. PID {pid:6d} ({display_name}): {total:8.1f}%%-s, "
                   f"Avg: {np.mean(percents):5.1f}%, Max: {np.max(percents):5.1f}%\n")
            f.write(f"      Command: {cmdline}\n")

    print(f"  Summary report saved to: {report_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Parse system performance log and generate visualizations")
    parser.add_argument("log_pattern", type=str,
                       help="Path to the performance log file (supports wildcards, e.g., sysperf*.log)")
    parser.add_argument("--output_dir", type=str, default=None,
                       help="Output directory for plots (default: same as log file name)")
    parser.add_argument("--top_n", type=int, default=20,
                       help="Number of top processes to plot individually (default: 20)")

    args = parser.parse_args()

    # 展开通配符模式
    log_files = glob.glob(args.log_pattern)

    if not log_files:
        print(f"Error: No log files found matching pattern: {args.log_pattern}")
        sys.exit(1)

    # 如果有多个文件，选择最新的（按修改时间）
    if len(log_files) > 1:
        log_files.sort(key=os.path.getmtime, reverse=True)
        print(f"Found {len(log_files)} log files, using the most recent:")
        for f in log_files[:min(5, len(log_files))]:
            mtime = os.path.getmtime(f)
            from datetime import datetime
            print(f"  {f} ({datetime.fromtimestamp(mtime)})")
        print()

    log_file = log_files[0]
    print(f"Using log file: {log_file}\n")

    # 确定输出目录：使用日志文件名（不含扩展名）作为输出目录名
    if args.output_dir is None:
        log_basename = os.path.basename(log_file)
        # 移除.log扩展名
        if log_basename.endswith('.log'):
            output_dir = log_basename[:-4]
        else:
            output_dir = log_basename
        # 如果是sysperf_*格式，使用其作为目录名
        if output_dir.startswith('sysperf_'):
            output_dir = output_dir
    else:
        output_dir = args.output_dir

    # 创建输出目录
    os.makedirs(output_dir, exist_ok=True)

    # 解析日志文件
    data = parse_log_file(log_file)

    if not data.cpu_data and not data.process_data:
        print("Error: No valid data found in log file")
        sys.exit(1)

    # 生成图表
    plot_cpu_performance(data, output_dir)
    plot_cpu_with_processes(data, output_dir)
    plot_process_performance(data, output_dir, args.top_n)
    generate_summary_report(data, output_dir)

    print("\n" + "=" * 60)
    print(f"All plots saved to: {output_dir}")
    print("=" * 60)


if __name__ == "__main__":
    main()
