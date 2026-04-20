#!/usr/bin/env python3
"""诊断 runtime_env.py 的同步问题"""

import re
import tempfile
from pathlib import Path

# 模拟实际 vmc.sh 的内容
VMC_CONTENT = """#!/bin/env bash

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
VMC_CMD="${HOME}/.vmc/bin/vmc"

export VMC_HOME="${HOME}/.vmc"
export VMC_SOFTWARE="${ROOT_DIR}"

# 包配置
MDRIVE_VEHICLE_MODEL=""
MDRIVE_VEHICLE_NAME=""
MDRIVE_VEHICLE_ID=""
MDRIVE_VERSION=""
MDRIVE_CONF_VERSION=""
MDRIVE_MODEL_VERSION=""
MDRIVE_MAP_VERSION=""

# export MDRIVE_VEHICLE_MODEL="${MDRIVE_VEHICLE_MODEL}"
export MDRIVE_VEHICLE_NAME="${MDRIVE_VEHICLE_NAME}"
export MDRIVE_VEHICLE_ID="${MDRIVE_VEHICLE_ID}"
"""


def _extract_vmc_value(vmc_text: str, key_name: str) -> str:
    """提取 vmc.sh 中的值"""
    matched_value = re.search(
        r"^{0}=(.*)$".format(key_name),
        vmc_text,
        flags=re.MULTILINE,
    )
    if matched_value is None:
        raise RuntimeError("vmc.sh 缺少必要字段: {0}".format(key_name))
    return matched_value.group(1).strip().strip('"')


def test_extract():
    """测试值提取"""
    print("=" * 60)
    print("测试 1: 值提取逻辑")
    print("=" * 60)

    keys = ["MDRIVE_VEHICLE_MODEL", "MDRIVE_VEHICLE_NAME", "MDRIVE_VERSION"]
    for key in keys:
        try:
            value = _extract_vmc_value(VMC_CONTENT, key)
            print(f"✓ {key} = {repr(value)}")
        except RuntimeError as e:
            print(f"✗ {key} - ERROR: {e}")


def test_sync():
    """测试同步逻辑"""
    print("\n" + "=" * 60)
    print("测试 2: 替换逻辑")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        vmc_path = Path(tmpdir) / "vmc.sh"
        vmc_path.write_text(VMC_CONTENT, encoding="utf-8")

        # 尝试替换所有字段
        target_values = {
            "MDRIVE_VEHICLE_MODEL": "E171",
            "MDRIVE_VEHICLE_NAME": "XZB600001",
            "MDRIVE_VERSION": "1.2.3",
            "MDRIVE_CONF_VERSION": "E171.2.3",
            "MDRIVE_MODEL_VERSION": "4.5.6",
            "MDRIVE_MAP_VERSION": "7.8.9",
        }

        vmc_text = vmc_path.read_text(encoding="utf-8")
        updated_text = vmc_text

        for key_name, value_text in target_values.items():
            replacement = "{0}={1}".format(
                key_name,
                '"{0}"'.format(value_text) if "VEHICLE_" in key_name else value_text,
            )
            print(f"\n替换 {key_name}:")
            print(f"  pattern: r'^{key_name}=.*$'")
            print(f"  replacement: {repr(replacement)}")

            old_lines = [line for line in updated_text.split("\n") if key_name in line]
            print(f"  原行数: {old_lines}")

            updated_text = re.sub(
                r"^{0}=.*$".format(key_name),
                replacement,
                updated_text,
                flags=re.MULTILINE,
            )

            new_lines = [line for line in updated_text.split("\n") if key_name in line]
            print(f"  新行数: {new_lines}")

            if replacement.lstrip('"').rstrip('"') in "\n".join(new_lines):
                print(f"  ✓ 替换成功")
            else:
                print(f"  ✗ 替换可能失败")

        vmc_path.write_text(updated_text, encoding="utf-8")

        # 验证最终结果
        print("\n" + "-" * 60)
        print("最终结果验证:")
        print("-" * 60)

        final_text = vmc_path.read_text(encoding="utf-8")
        for key_name, value_text in target_values.items():
            try:
                actual_value = _extract_vmc_value(final_text, key_name)
                if actual_value == value_text:
                    print(f"✓ {key_name} = {repr(actual_value)} (正确)")
                else:
                    print(
                        f"✗ {key_name} = {repr(actual_value)} (期望: {repr(value_text)})"
                    )
            except RuntimeError as e:
                print(f"✗ {key_name} - ERROR: {e}")


def test_edge_cases():
    """测试边界情况"""
    print("\n" + "=" * 60)
    print("测试 3: 边界情况")
    print("=" * 60)

    # 测试带注释的行
    test_content = """
MDRIVE_VERSION=""  # 这是注释
MDRIVE_CONF_VERSION=old_conf # another comment
MDRIVE_MODEL_VERSION=  # empty value with comment
"""

    print("\n测试内容:")
    print(test_content)

    for key in ["MDRIVE_VERSION", "MDRIVE_CONF_VERSION", "MDRIVE_MODEL_VERSION"]:
        try:
            value = _extract_vmc_value(test_content, key)
            print(f"{key} = {repr(value)}")
        except RuntimeError as e:
            print(f"{key} - ERROR: {e}")


if __name__ == "__main__":
    test_extract()
    test_sync()
    test_edge_cases()
