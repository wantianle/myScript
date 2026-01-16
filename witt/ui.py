def print_banner():
    print("" + "=" * 42)
    print("               witt  v1.0")
    print("            What Is That Tag?")
    print("=" * 42)


def print_menu():
    print("  1. 查询 -> 压缩/切片/下载 -> 同步/回放")
    print("  2. [仅查询] 查询 tag 对应 record 文件")
    print("  3. [仅压缩] 指定文件过滤 Channel")
    print("  4. [仅切片] 指定目录对时间切片")
    print("  5. [仅同步] 同步本地 docker 环境")
    print("  6. [仅回播] 查询并回播已处理数据")
    print("  h. [说明文档]")
    print("  q. 退出")
    print("=" * 42)


def show_playback_library(library, vehicle, target_date):
    """专门负责打印播放列表"""
    print(f"\n{'ID '} | {vehicle:<9} | {target_date}")
    print("-" * 42)

    count = 1
    for entry in library:
        if entry["date"] == target_date and entry["vehicle"] == vehicle:
            print(
                f"{count:<3} ├── \033[3m{entry['time'][11:]} \033[1;32m{entry['tag']}\033[0m "
            )

            indent = " " * 4
            meta = entry.get("fast_meta", {}).get("last_update", {})
            soc1_update = meta.get("soc1", "N/A")
            soc2_update = meta.get("soc2", "N/A")

            print(f"{indent}├── soc1 update: \033[1;33m{soc1_update}\033[0m")
            print(f"{indent}└── soc2 update: \033[1;33m{soc2_update}\033[0m")
            count += 1


def show_channel_table(channels):
    """打印 Channel 列表表格"""
    print("-" * 72)
    print(f"{'ID':<4} | {'Channel Name':<55} | {'Messages'}")
    print("-" * 72)
    for i, ch in enumerate(channels, 1):
        print(f"{i:<4} | {ch['name']:<55} | {ch['count']}")
    print("-" * 72)


def show_manual_play_header():
    print("\n" + "=" * 20 + " 手动回播模式 " + "=" * 20)
    print("提示: 直接将多个 record 文件/文件夹拖入终端，回车确认 | 'q' 返回")


def show_playback_info(tag, duration, channels=None):
    print(f"\n当前回播: \033[1;32m{tag}\033[0m")
    print(f"总时长: \033[1;33m{duration}s\033[0m")
    if channels:
        print(f"频道过滤: \033[1;34m{channels}\033[0m")


def print_status(msg, level="INFO"):
    """
    终端即时反馈，不进入日志文件。
    """
    colors = {
        "INFO": "\033[32m",
        "WARN": "\033[33m",
        "ERR": "\033[31m",
        "RESET": "\033[0m",
    }
    print(f"{colors.get(level, '')}[{level}] {msg}{colors['RESET']}")


def notify_operation(op_name, details):
    """
    专门用于告知用户正在进行繁重操作。
    """
    print(f"\n\033[1;34m>>> 正在执行: {op_name}\033[0m")
    for k, v in details.items():
        print(f"    {k}: {v}")
