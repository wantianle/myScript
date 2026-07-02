#!/usr/bin/env python3
"""将 CSV 版本管理表格的分支信息直接写回 config/mdrive4/ 下的各模块 JSON 文件"""

import csv
import json
import sys
from pathlib import Path


def apply_csv(csv_path: str, modules_dir: str | None = None) -> None:
    csv_path = Path(csv_path)
    if not csv_path.exists():
        print(f"错误: 文件不存在 {csv_path}", file=sys.stderr)
        sys.exit(1)

    if modules_dir is None:
        modules_dir = csv_path.parent
    modules_dir = Path(modules_dir)

    # 读取 CSV，构建 module -> component -> branch 映射
    branch_map: dict[str, dict[str, str]] = {}
    current_module = ""
    with csv_path.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            module = (row.get("module") or "").strip()
            component = (row.get("component") or "").strip()
            branch = (row.get("branch") or "").strip()
            if not component:
                continue
            if module:
                current_module = module
            if not current_module:
                continue
            branch_map.setdefault(current_module, {})[component] = branch

    # 自动检测模块目录: 若首个模块文件不存在，尝试子目录
    first_group = next(iter(branch_map))
    first_file = modules_dir / f"{first_group}_modules.json"
    if not first_file.exists():
        for sub in sorted(modules_dir.iterdir()):
            if sub.is_dir() and (sub / f"{first_group}_modules.json").exists():
                modules_dir = sub
                break

    # 回写各模块 JSON
    updated_count = 0
    not_found: list[str] = []

    for module_group, components in branch_map.items():
        module_file = modules_dir / f"{module_group}_modules.json"
        if not module_file.exists():
            print(f"警告: 未找到模块文件 {module_file}，跳过")
            continue

        with module_file.open(encoding="utf-8") as f:
            data = json.load(f)

        changed = False
        for mod in data["modules"]:
            comp = mod["component"]
            if comp in components:
                new_branch = components[comp]
                old_branch = mod.get("branch", "")
                if old_branch != new_branch:
                    mod["branch"] = new_branch
                    changed = True
                    updated_count += 1
                    print(f"  [{module_group}] {comp}: {old_branch} -> {new_branch}")

        if changed:
            with module_file.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
                f.write("\n")
            print(f"已更新: {module_file.name}")

    # 检查未匹配到的组件
    for module_group, components in branch_map.items():
        module_file = modules_dir / f"{module_group}_modules.json"
        if not module_file.exists():
            continue
        with module_file.open(encoding="utf-8") as f:
            data = json.load(f)
        existing = {m["component"] for m in data["modules"]}
        for comp in components:
            if comp not in existing:
                not_found.append(f"{module_group}/{comp}")

    for item in not_found:
        print(f"警告: 未在对应模块文件中找到组件 {item}")

    print(f"\n完成! 共更新 {updated_count} 个组件的分支")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python apply_branch_json.py <csv文件路径> [模块目录]")
        print("示例: python apply_branch_json.py ../mdrive4/mdrive4_branch_template.csv ../mdrive4/")
        sys.exit(1)
    apply_csv(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
