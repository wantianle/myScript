#!/usr/bin/env python3
"""
update_vehicle_cfg.py - 批量更新车辆配置

从 mdrive_conf (~/dev/mdrive_conf) 读取各车辆的实际 vin 和 RTK 账户，
更新 vehicle_cfg (~/dev/mdrive4/vehicle_cfg) 下对应车辆的:
  1. calib/*.json          — 填入 vehicle_id + vin
  2. vehicle_config.pb.txt  — 填入 model, id, vin, plate
  3. ntrip_conf.pb.txt      — 按账户类型写入千寻或华测模板

数据来源: ~/dev/mdrive_conf/{model}/vehicle_name/{id}/gnss_ntrip.pb.txt
          ~/dev/mdrive_conf/{model}/vehicle_name/{id}/vehicle_config.pb.txt

用法:
    python3 update_vehicle_cfg.py XZT500008               # 单个车辆
    python3 update_vehicle_cfg.py XZT500008 XZT500009     # 多个车辆
    python3 update_vehicle_cfg.py XZT500008-XZT500017     # 范围
    python3 update_vehicle_cfg.py all                     # 全部

参数:
    --mdrive-conf    mdrive_conf 目录路径 (默认: ~/dev/mdrive_conf)
    --vehicle-root   车辆配置根目录 (默认: ~/dev/mdrive4/vehicle_cfg/vehicle)
"""

import argparse
import json
import re
import sys
from pathlib import Path



# ============================================================
# 配置
# ============================================================

MDRIVE_CONF_PATH = Path.home() / "dev/mdrive_conf"
VEHICLE_ROOT = Path.home() / "dev/mdrive4/vehicle_cfg/vehicle"

# 千寻 (Qianxun) NTRIP 配置模板
QIANXUN_TEMPLATE = """\
ntrip_address: "rtk.ntrip.qxwz.com"
ntrip_port: 8002
mount_point: "AUTO"
account: "{account}"
password: "{password}"
gpgga_channel_name: "/sensor/gnss/gpgga"
rtcm_channel_name: "/sensor/cors/rtcm"
dns_server: ""
source_ip: ""
reconnect_interval_ms: 1000\
"""

# 华测 (Huace) NTRIP 配置模板
HUACE_TEMPLATE = """\
ntrip_address: "rtk.huacenav.com"
ntrip_port: 8002
mount_point: "RTCM33"
account: "{account}"
password: "{password}"
gpgga_channel_name: "/sensor/gnss/gpgga"
rtcm_channel_name: "/sensor/cors/rtcm"
dns_server: ""
source_ip: ""
reconnect_interval_ms: 1000\
"""

# ============================================================
# mdrive_conf 数据读取
# ============================================================

def _extract_field(content: str, field: str) -> str:
    """从 protobuf text 中提取字段值, 如 user: "qxykhy0018150" -> qxykhy0018150"""
    m = re.search(rf'{field}:\s*"([^"]*)"', content)
    return m.group(1) if m else ""


def _is_rtk_empty(user: str) -> bool:
    """RTK 账户为空/占位符"""
    return not user or user == "xxx"


def load_mdrive_conf_data(mdrive_conf_path: Path) -> dict:
    """扫描 mdrive_conf 目录, 从各车辆的 gnss_ntrip.pb.txt 和 vehicle_config.pb.txt 读取数据

    目录结构: mdrive_conf/{model}/vehicle_name/{vehicle_id}/
      - gnss_ntrip.pb.txt: 提取 user (RTK账户) 和 password
      - vehicle_config.pb.txt: 提取 vin

    返回 {车辆编号: {vin, rtk_account, rtk_password}}
    注意: vehicle_id 可能在不同 model 下重复, 取先遇到的
    """
    if not mdrive_conf_path.exists():
        print(f"[ERROR] mdrive_conf 目录不存在: {mdrive_conf_path}")
        sys.exit(1)

    registry = {}
    for model_dir in sorted(mdrive_conf_path.iterdir()):
        vn_dir = model_dir / "vehicle_name"
        if not vn_dir.is_dir():
            continue
        for vehicle_dir in sorted(vn_dir.iterdir()):
            if not vehicle_dir.is_dir():
                continue
            vehicle_name = vehicle_dir.name

            if vehicle_name in registry:
                continue  # 已从其他 model 读取, 跳过

            # 读取 vin
            vc_file = vehicle_dir / "vehicle_config.pb.txt"
            vin = ""
            if vc_file.exists():
                vin = _extract_field(vc_file.read_text(encoding="utf-8"), "vin")

            # 读取 RTK 账户
            gnss_file = vehicle_dir / "gnss_ntrip.pb.txt"
            rtk_account = ""
            rtk_password = ""
            if gnss_file.exists():
                content = gnss_file.read_text(encoding="utf-8")
                user = _extract_field(content, "user")
                password = _extract_field(content, "password")
                if not _is_rtk_empty(user):
                    rtk_account = user
                    rtk_password = password

            registry[vehicle_name] = {
                "vin": vin,
                "rtk_account": rtk_account,
                "rtk_password": rtk_password,
            }

    return registry


# ============================================================
# 参数解析
# ============================================================

def parse_vehicle_args(args: list, vehicle_dir_names: set) -> list:
    """解析命令行参数，支持: 单个编号、多个编号、范围(X-Y)、all"""
    result = []
    for arg in args:
        arg = arg.strip()
        if arg.lower() == "all":
            result.extend(sorted(vehicle_dir_names))
        elif "-" in arg and not arg.startswith("-"):
            # 范围: XZT500008-XZT500017
            match = re.match(r"^(XZT\d+)-(XZT\d+)$", arg)
            if match:
                prefix_start = re.match(r"(XZT)(\d+)", match.group(1))
                prefix_end = re.match(r"(XZT)(\d+)", match.group(2))
                if prefix_start and prefix_end:
                    prefix = prefix_start.group(1)
                    start_num = int(prefix_start.group(2))
                    end_num = int(prefix_end.group(2))
                    for n in range(start_num, end_num + 1):
                        name = f"{prefix}{n:0{len(prefix_start.group(2))}d}"
                        if name in vehicle_dir_names:
                            result.append(name)
                        else:
                            print(f"[WARN] 范围内车辆 {name} 不存在配置文件夹, 跳过")
                else:
                    print(f"[ERROR] 无法解析范围参数: {arg}")
            else:
                print(f"[ERROR] 无法解析参数: {arg}")
        else:
            # 单个编号
            if arg in vehicle_dir_names:
                result.append(arg)
            else:
                print(f"[WARN] 车辆 {arg} 不存在配置文件夹, 跳过")

    # 去重并保持顺序
    seen = set()
    unique = []
    for v in result:
        if v not in seen:
            seen.add(v)
            unique.append(v)
    return unique


def scan_vehicle_dirs(vehicle_root: Path) -> dict:
    """扫描所有车辆配置文件夹, 返回 {车辆编号: {model, path}}"""
    vehicles = {}
    for model_dir in sorted(vehicle_root.iterdir()):
        if not model_dir.is_dir():
            continue
        model = model_dir.name
        for vehicle_dir in sorted(model_dir.iterdir()):
            if not vehicle_dir.is_dir():
                continue
            vehicle_name = vehicle_dir.name
            vehicles[vehicle_name] = {
                "model": model,
                "path": vehicle_dir,
            }
    return vehicles


# ============================================================
# 文件更新
# ============================================================

def update_calib_files(calib_dir: Path, vehicle_id: str, vin: str) -> int:
    """更新 calib 目录下所有 JSON 文件的 vehicle_id 和 vin 字段, 返回更新文件数"""
    if not calib_dir.exists():
        print(f"  [WARN] calib 目录不存在: {calib_dir}")
        return 0

    count = 0
    for json_file in sorted(calib_dir.glob("*.json")):
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            updated = False
            if "vehicle_id" in data:
                data["vehicle_id"] = vehicle_id
                updated = True
            if "vin" in data:
                data["vin"] = vin
                updated = True

            if updated:
                with open(json_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
                    f.write("\n")
                count += 1
        except Exception as e:
            print(f"  [ERROR] 更新 {json_file.name} 失败: {e}")

    return count


def update_vehicle_config(config_path: Path, model: str, vehicle_id: str, vin: str) -> bool:
    """更新 vehicle_config.pb.txt 中的 vehicle_info 部分

    目标字段:
      vehicle_info {
        model: "..."
        id: "..."
        vin: "..."
        plate: ""
      }
    """
    if not config_path.exists():
        print(f"  [WARN] vehicle_config.pb.txt 不存在: {config_path}")
        return False

    try:
        content = config_path.read_text(encoding="utf-8")

        # 替换 vehicle_info 块内的四个字段
        # model
        content = re.sub(
            r'(model:\s*")[^"]*(")',
            rf'\g<1>{model}\g<2>',
            content,
            count=1,
        )
        # id
        content = re.sub(
            r'(id:\s*")[^"]*(")',
            rf'\g<1>{vehicle_id}\g<2>',
            content,
            count=1,
        )
        # vin
        content = re.sub(
            r'(vin:\s*")[^"]*(")',
            rf'\g<1>{vin}\g<2>',
            content,
            count=1,
        )
        # plate (always empty)
        content = re.sub(
            r'(plate:\s*")[^"]*(")',
            r'\g<1>\g<2>',
            content,
            count=1,
        )

        config_path.write_text(content, encoding="utf-8")
        return True
    except Exception as e:
        print(f"  [ERROR] 更新 vehicle_config.pb.txt 失败: {e}")
        return False


def update_ntrip_conf(ntrip_path: Path, rtk_account: str, rtk_password: str) -> str:
    """更新 ntrip_conf.pb.txt, 返回状态描述字符串

    逻辑:
    - 如果 RTK 账户以 qxykhy 开头 (千寻):
        写入千寻配置, 使用查到的账户和密码
    - 如果 RTK 账户以 yjcx 开头 (华测):
        写入华测配置, 使用查到的账户和密码
    - 如果没有 RTK 账户:
        写入千寻配置, 账户和密码留空
    """
    if not ntrip_path.exists():
        print(f"  [WARN] ntrip_conf.pb.txt 不存在: {ntrip_path}")
        return "文件不存在"

    if rtk_account.startswith("qxykhy"):
        template = QIANXUN_TEMPLATE
        account = rtk_account
        password = rtk_password
        status = f"千寻: {account}/{password}"
    elif rtk_account.startswith("yjcx"):
        template = HUACE_TEMPLATE
        account = rtk_account
        password = rtk_password
        status = f"华测: {account}/{password}"
    else:
        template = QIANXUN_TEMPLATE
        account = ""
        password = ""
        status = "千寻: (空)"

    content = template.format(account=account, password=password) + "\n"
    ntrip_path.write_text(content, encoding="utf-8")
    return status


# ============================================================
# 主流程
# ============================================================

def process_vehicle(vehicle_name: str, vehicle_info: dict, registry: dict) -> None:
    """处理单个车辆的所有配置更新"""
    vehicle_path = vehicle_info["path"]
    model = vehicle_info["model"]
    calib_dir = vehicle_path / "calib"

    # 查 Excel
    record = registry.get(vehicle_name, {})
    vin = record.get("vin", "")
    rtk_account = record.get("rtk_account", "")
    rtk_password = record.get("rtk_password", "")

    warnings = []
    if not record:
        warnings.append(f"车辆 {vehicle_name} 在 mdrive_conf 中查不到, vin 将留空")
    if not vin:
        warnings.append(f"车辆 {vehicle_name} VIN 为空")
    if not rtk_account:
        warnings.append(f"车辆 {vehicle_name} RTK 账户为空, ntrip 将写入空账户千寻配置")

    print(f"\n{'='*60}")
    print(f"[处理] {vehicle_name} (model={model})")
    for w in warnings:
        print(f"  [WARN] {w}")

    # 1. 更新 calib 文件
    calib_count = update_calib_files(calib_dir, vehicle_name, vin)
    print(f"  [calib] 更新了 {calib_count} 个文件 (vehicle_id={vehicle_name}, vin={vin or '(空)'})")

    # 2. 更新 vehicle_config.pb.txt
    vc_path = vehicle_path / "vehicle_config.pb.txt"
    if update_vehicle_config(vc_path, model, vehicle_name, vin):
        print(f"  [vehicle_config] 已更新 (model={model}, id={vehicle_name}, vin={vin or '(空)'})")

    # 3. 更新 ntrip_conf.pb.txt
    ntrip_path = vehicle_path / "ntrip_conf.pb.txt"
    ntrip_status = update_ntrip_conf(ntrip_path, rtk_account, rtk_password)
    print(f"  [ntrip_conf] {ntrip_status}")


def main():
    parser = argparse.ArgumentParser(
        description="批量更新车辆配置 (calib, vehicle_config.pb.txt, ntrip_conf.pb.txt)",
        epilog="示例: %(prog)s XZT500008 | %(prog)s XZT500008-XZT500017 | %(prog)s all",
    )
    parser.add_argument(
        "vehicles",
        nargs="+",
        help="车辆编号, 支持: 单个编号 / 多个编号 / 范围(X-Y) / all",
    )
    parser.add_argument(
        "--mdrive-conf",
        default=str(MDRIVE_CONF_PATH),
        help=f"mdrive_conf 目录路径 (默认: {MDRIVE_CONF_PATH})",
    )
    parser.add_argument(
        "--vehicle-root",
        default=str(VEHICLE_ROOT),
        help=f"车辆配置根目录 (默认: {VEHICLE_ROOT})",
    )

    args = parser.parse_args()
    mdrive_conf_path = Path(args.mdrive_conf)
    vehicle_root = Path(args.vehicle_root)

    # 加载数据
    print(f"[加载] 读取 mdrive_conf: {mdrive_conf_path}")
    registry = load_mdrive_conf_data(mdrive_conf_path)
    print(f"[加载] mdrive_conf 中共 {len(registry)} 条车辆记录")

    print(f"[加载] 扫描车辆配置目录: {vehicle_root}")
    vehicle_dirs = scan_vehicle_dirs(vehicle_root)
    print(f"[加载] 共发现 {len(vehicle_dirs)} 个车辆配置文件夹")
    for name in sorted(vehicle_dirs):
        print(f"  {vehicle_dirs[name]['model']}/{name}")

    # 解析参数
    target_vehicles = parse_vehicle_args(args.vehicles, set(vehicle_dirs.keys()))
    if not target_vehicles:
        print("\n[ERROR] 没有找到匹配的车辆配置文件夹")
        sys.exit(1)

    print(f"\n[目标] 共 {len(target_vehicles)} 辆车待处理: {', '.join(target_vehicles)}")
    print("[即将开始直接修改文件...]")

    # 处理
    success = 0
    fail = 0
    for vehicle_name in target_vehicles:
        try:
            process_vehicle(vehicle_name, vehicle_dirs[vehicle_name], registry)
            success += 1
        except Exception as e:
            print(f"  [ERROR] 处理 {vehicle_name} 失败: {e}")
            fail += 1

    print(f"\n{'='*60}")
    print(f"[完成] 成功: {success}, 失败: {fail}")
    if fail > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
