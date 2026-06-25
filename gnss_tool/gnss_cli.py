#!/usr/bin/env python3
"""
GNSS/INS 组合导航配置工具 — 命令行入口

用法:
  python3 gnss_cli.py           默认配置模式：写入所有参数并保存
  python3 gnss_cli.py status    状态模式：只读取，不写入
  python3 gnss_cli.py check     检查模式：检查 GPCHC RTK 状态
"""

import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gnss_telnet import NavDevice
import gnss_config as cfg


# ═══════════════════════════════════════════════════════════
#  阶段执行
# ═══════════════════════════════════════════════════════════

def run_phase(dev, title, commands):
    """发送一组命令，逐行显示 ok 确认"""
    print("\n── " + title + " ──")
    fail_count = 0
    for cmd in commands:
        ok, resp = dev.cmd(cmd)
        mark = "✓" if ok else "✗"
        last = resp.strip().split("\n")[-1] if resp else "(无响应)"
        print("  {} {:50s} → {}".format(mark, cmd, last.strip()))
        if not ok:
            fail_count += 1
    return fail_count


def do_saveconfig(dev, label=""):
    ok, resp = dev.cmd("saveconfig")
    mark = "✓" if ok else "✗"
    tag = "(" + label + ")" if label else ""
    print("  {} saveconfig {}".format(mark, tag))
    return ok


# ═══════════════════════════════════════════════════════════
#  模式: 配置
# ═══════════════════════════════════════════════════════════

def mode_configure(dev):
    total_fail = 0

    # ── 0. 查看并清除旧日志配置 ──
    print("\n── 当前日志输出配置 ──")
    ok, data = dev.cmd("log loglist")
    if data:
        for line in data.strip().split("\n"):
            print("  " + line.strip())
    else:
        print("  (无法读取)")

    print("\n── 清除所有日志输出 ──")
    ok, _ = dev.cmd("unlogall")
    print("  unlogall → " + ("✓" if ok else "✗ (继续执行，不影响后续配置)"))
    # unlogall 失败不计数，不影响后续流程

    phases = [
        ("阶段 1/4: 周期性日志输出", [cmd for cmd in cfg.LOG_PERIODIC]),
        ("阶段 2/4: 事件触发日志输出", [cmd for cmd in cfg.LOG_EVENT]),
        ("阶段 3/4: 杆臂/安装参数",
         ["{} {}".format(k, v) for k, v in cfg.CALIB_PARAMS.items()]),
        ("阶段 4/4: 收尾操作", [cmd for cmd in cfg.FINAL_COMMANDS]),
    ]
    save_keys = ["LOG_PERIODIC", "LOG_EVENT", "CALIB_PARAMS", "FINAL_COMMANDS"]

    for idx, (title, cmds) in enumerate(phases):
        if not cmds:
            continue
        total_fail += run_phase(dev, title, cmds)
        if cfg.SAVE_AFTER.get(save_keys[idx], False):
            do_saveconfig(dev)

    # ── 额外保险: 最后 double saveconfig ──
    print("\n── 最终保存（double check）──")
    ok1 = do_saveconfig(dev, "第1次")
    ok2 = do_saveconfig(dev, "第2次")

    if total_fail == 0 and ok1 and ok2:
        print("\n═══════════════════════════════════")
        print("  全部配置完成 ✓")
        print("═══════════════════════════════════")
    else:
        print("\n⚠ 配置有 {} 个命令失败，请检查上面输出".format(total_fail))

    # ── 回读确认 ──
    mode_status(dev)


# ═══════════════════════════════════════════════════════════
#  模式: 状态（只读）
# ═══════════════════════════════════════════════════════════

def mode_status(dev):
    print("\n╔══════════════════════════════════════════╗")
    print("║           设备状态汇总                    ║")
    print("╚══════════════════════════════════════════╝")

    # 1. interface
    print("\n── interface ──")
    ok, data = dev.read_interface()
    if data:
        for line in data.strip().split("\n"):
            print("  " + line.strip())
    else:
        print("  (无输出)")

    # 2. getting version
    print("\n── getting version ──")
    ver = dev.read_version()
    for k, v in ver.items():
        if k == "raw":
            for line in v.strip().split("\n")[:3]:
                print("  " + line.strip())
        else:
            print("  {}: {}".format(k, v))

    # 3. getting gilccfg
    print("\n── getting gilccfg ──")
    gilcfg = dev.read_config()
    for section, items in gilcfg.get("sections", {}).items():
        print("  [" + section + "]")
        for k, v in items.items():
            print("    {}: {}".format(k, v))

    # 4. log loglist
    print("\n── log loglist ──")
    logs = dev.read_loglist()
    if logs:
        for entry in logs:
            print("  {:20s} {:6s} {}".format(entry["name"], entry["port"], entry["rate"]))
    else:
        print("  (无日志输出配置)")

    # 5. log gpchcx once
    print("\n── log gpchcx once ──")
    ok, gpchcx = dev.read_gpchcx_once()
    if gpchcx:
        for line in gpchcx.strip().split("\n")[:5]:
            print("  " + line.strip())
    else:
        print("  (无输出)")


# ═══════════════════════════════════════════════════════════
#  模式: 检查
# ═══════════════════════════════════════════════════════════

def mode_check(dev):
    print("检查 GPCHC RTK 状态...\n")
    result = dev.check_gpchc_status()

    # 打印原始数据
    print("── 原始数据 ──")
    for line in result["raw"].strip().split("\n"):
        print("  " + line.strip())

    print("\n── 状态分析 ──")
    if result["status_hex"] is not None:
        print("  Status 字段: 0x{:02X}".format(result["status_hex"]))
    else:
        print("  Status 字段: 解析失败")
    print("  结果: " + result["message"])

    if result["rtk_fixed"]:
        print("\n  ✓ RTK 状态正常")
    elif result["status_hex"] == 0x61:
        print("\n  ✗ 无 RTK 输出 — 请检查:")
        print("    1. 差分账号是否已配置 (CORS_LOGIN)")
        print("    2. 网络是否连通 (interface)")
        print("    3. 日志输出是否包含 RTK 相关消息")
    else:
        print("\n  - 非理想状态，请确认差分配置")


# ═══════════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="GNSS/INS CGI-230 组合导航配置工具")
    parser.add_argument("mode", nargs="?", default="config",
                        choices=["config", "status", "check"],
                        help="模式: config(默认/写入配置), status(只读状态), check(检查RTK)")
    args = parser.parse_args()

    dev = NavDevice(host=cfg.HOST, port=cfg.PORT)
    print("连接 {}:{} ...".format(cfg.HOST, cfg.PORT))
    try:
        dev.connect()
        print("已连接")

        if args.mode == "config":
            mode_configure(dev)
        elif args.mode == "status":
            mode_status(dev)
        elif args.mode == "check":
            mode_check(dev)

    except Exception as e:
        print("\n✗ 错误: " + str(e))
        sys.exit(1)
    finally:
        dev.close()
        print("\n连接已关闭")


if __name__ == "__main__":
    main()
