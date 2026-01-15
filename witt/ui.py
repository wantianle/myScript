import logging
from rich.console import Console
from rich.table import Table

console = Console()


class Formatter(logging.Formatter):
    """处理颜色与格式"""

    COLORS = {
        "DEBUG": "\033[0;90m",
        "INFO": "\033[0;32m",
        "WARNING": "\033[0;33m",
        "ERROR": "\033[0;31m",
        "RESET": "\033[0m",
    }

    def format(self, record):
        color = self.COLORS.get(record.levelname, self.COLORS["RESET"])
        fmt = f"{color}[%(levelname)s] %(message)s{self.COLORS['RESET']}"
        return logging.Formatter(fmt).format(record)


def print_banner():
    print("\n" + "=" * 50)
    print("               witt  v1.0")
    print("            What Is That Tag?")
    print("=" * 50)


def print_menu():
    print("  1. 查询 -> 压缩/切片/下载 -> 同步/回放")
    print("  2. [仅查询] 查询 tag 对应 record 文件")
    print("  3. [仅压缩] 指定文件过滤 Channel")
    print("  4. [仅切片] 指定目录对时间切片")
    print("  5. [仅同步] 同步本地 docker 环境")
    print("  6. [仅回播] 查询并回播已处理数据")
    print("  h. [说明文档]")
    print("  q. 退出")
    print("=" * 50)


def show_playback_library(library, vehicle, target_date):
    """专门负责打印那个漂亮的播放列表"""
    print(f"\n{'ID '} | {vehicle:<9} | {target_date}")
    print("-" * 65)

    count = 1
    for entry in library:
        if entry["date"] == target_date and entry["vehicle"] == vehicle:
            print(
                f"{count:<3} ├── \033[3m{entry['time'][11:]} \033[1;32m{entry['tag']}\033[0m "
            )

            # 打印 SOC 更新时间
            indent = " " * 4
            meta = entry.get("fast_meta", {}).get("last_update", {})
            soc1_update = meta.get("soc1", "N/A")
            soc2_update = meta.get("soc2", "N/A")

            print(f"{indent}├── soc1 update: \033[1;33m{soc1_update}\033[0m")
            print(f"{indent}└── soc2 update: \033[1;33m{soc2_update}\033[0m")
            count += 1
    # return count - 1  # 返回显示的任务总数


def show_tasks_table(tasks):
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("ID", style="dim", width=6)
    table.add_column("Time", style="cyan")
    table.add_column("Tag Name", style="green")

    for t in tasks:
        table.add_row(t["id"], t["time"], t["name"])

    console.print(table)


def show_channel_table(channels):
    """打印 Channel 列表表格"""
    print("-" * 72)
    print(f"{'ID':<4} | {'Channel Name':<55} | {'Messages'}")
    print("-" * 72)
    for i, ch in enumerate(channels, 1):
        print(f"{i:<4} | {ch['name']:<55} | {ch['count']}")

