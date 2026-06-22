#!/usr/bin/env python3

import argparse
import glob
import json
import os
import sys
from collections import OrderedDict


def find_json(path_or_glob):
    """解析参数，返回 (label, json_path)。
    支持:
      - 直接传 app_version.json 文件路径
      - 传目录，自动拼接 app_version.json
      - 通配符，匹配目录后拼接 app_version.json
    """
    # 如果直接指向 .json 文件
    if path_or_glob.endswith('.json') and os.path.isfile(path_or_glob):
        return os.path.basename(path_or_glob), path_or_glob

    # glob 匹配目录
    matches = sorted(glob.glob(path_or_glob))
    dirs = [m for m in matches if os.path.isdir(m) and os.path.isfile(os.path.join(m, "app_version.json"))]
    if not dirs:
        # 最后尝试把参数本身当作目录
        json_path = os.path.join(path_or_glob, "app_version.json")
        if os.path.isfile(json_path):
            return path_or_glob, json_path
        print(f"错误: 找不到匹配的目录 (含 app_version.json): {path_or_glob}")
        print(f"  glob 匹配到: {matches}")
        sys.exit(1)

    if len(dirs) > 1:
        print(f"注意: 通配符 '{path_or_glob}' 匹配到 {len(dirs)} 个目录，取第一个:")
        print(f"  -> {dirs[0]}")

    label = os.path.basename(dirs[0])
    json_path = os.path.join(dirs[0], "app_version.json")
    return label, json_path


def _extract_branch(dirname):
    """从目录名提取分支前缀，如 master-P401273-... → master"""
    import re
    # 取 -P+数字 之前的部分作为分支名
    m = re.match(r"^(.+?)-P\d+", dirname)
    return m.group(1) if m else dirname


def auto_discover(search_dir="."):
    """自动搜索当前目录下含 app_version.json 的目录。
    只有2个时直接用；>2个时检查是否同分支，同分支取首尾，跨分支报错。
    """
    candidates = []
    for d in os.listdir(search_dir):
        full = os.path.join(search_dir, d)
        if os.path.isdir(full) and os.path.isfile(os.path.join(full, "app_version.json")):
            candidates.append(d)

    if len(candidates) < 2:
        print(f"错误: 需要在当前目录至少有2个含 app_version.json 的目录，当前找到 {len(candidates)} 个")
        print(f"  找到: {candidates}")
        print("\n用法: python3 compare_versions.py <旧目录> <新目录>")
        sys.exit(1)

    candidates.sort()

    if len(candidates) == 2:
        old_dir, new_dir = candidates[0], candidates[1]
    else:
        # 按分支名分组
        groups = {}
        for c in candidates:
            branch = _extract_branch(c)
            groups.setdefault(branch, []).append(c)

        if len(groups) > 1:
            print(f"错误: 发现 {len(candidates)} 个目录，分属 {len(groups)} 个不同分支，无法自动判断:")
            for branch, dirs in groups.items():
                print(f"  [{branch}]")
                for d in dirs:
                    print(f"    {d}")
            print(f"\n请明确指定要对比的两个目录，例如:")
            first_branch = list(groups.keys())[0]
            dirs = groups[first_branch]
            if len(dirs) >= 2:
                print(f"  python3 compare_versions.py '{dirs[0]}' '{dirs[-1]}'")
            sys.exit(1)

        # 同分支，取首尾
        branch = list(groups.keys())[0]
        dirs = groups[branch]
        old_dir, new_dir = dirs[0], dirs[-1]
        if len(dirs) > 2:
            print(f"分支 [{branch}] 下发现 {len(dirs)} 个目录，取最早和最晚:")
            for d in dirs:
                tag = " ← 旧" if d == old_dir else (" ← 新" if d == new_dir else "")
                print(f"  {d}{tag}")

    old_label, old_path = old_dir, os.path.join(search_dir, old_dir, "app_version.json")
    new_label, new_path = new_dir, os.path.join(search_dir, new_dir, "app_version.json")
    return old_label, old_path, new_label, new_path


def build_repo_map(data):
    """从 JSON 数据构建 (component, system) -> repo info 的映射。"""
    repo_map = OrderedDict()
    for system_entry in data.get("systems", []):
        for repo in system_entry.get("repos", []):
            component = repo.get("component", "")
            key = (component, repo.get("system", ""))
            repo_map[key] = {
                "component": component,
                "branch": repo.get("branch", ""),
                "system": repo.get("system", ""),
                "commit_id": repo.get("commit_id", ""),
            }
    return repo_map


def compare(old_data, new_data):
    """对比两份数据，返回差异列表。"""
    old_repos = build_repo_map(old_data)
    new_repos = build_repo_map(new_data)

    differences = []
    added = []
    removed = []

    for key in old_repos:
        if key in new_repos:
            old_item = old_repos[key]
            new_item = new_repos[key]
            if old_item["commit_id"] != new_item["commit_id"]:
                diff = {
                    "component": old_item["component"],
                    "system": old_item["system"],
                    "branch": new_item["branch"],
                    "old_commit_id": old_item["commit_id"],
                    "new_commit_id": new_item["commit_id"],
                }
                if old_item["branch"] != new_item["branch"]:
                    diff["old_branch"] = old_item["branch"]
                differences.append(diff)
        else:
            removed.append({
                "component": old_repos[key]["component"],
                "system": old_repos[key]["system"],
                "branch": old_repos[key]["branch"],
                "commit_id": old_repos[key]["commit_id"],
            })

    for key in new_repos:
        if key not in old_repos:
            added.append({
                "component": new_repos[key]["component"],
                "system": new_repos[key]["system"],
                "branch": new_repos[key]["branch"],
                "commit_id": new_repos[key]["commit_id"],
            })

    return old_repos, new_repos, differences, added, removed


def generate_markdown(old_label, new_label, old_repos, new_repos, differences, added, removed, output_path):
    """生成 Markdown 报告。"""
    sys_summary = {}
    for d in differences:
        sys_name = d["system"]
        sys_summary.setdefault(sys_name, []).append(d["component"])

    lines = [
        "# 版本对比报告",
        "",
        f"**旧版本:** `{old_label}`  ",
        f"**新版本:** `{new_label}`  ",
        "",
        "---",
        "",
        "## 对比概要",
        "",
        "| 指标 | 数量 |",
        "|------|------|",
        f"| 总对比 repos | {len(old_repos)} |",
        f"| commit_id 变更 | **{len(differences)}** |",
        f"| 新增 | {len(added)} |",
        f"| 移除 | {len(removed)} |",
    ]

    if differences:
        lines += [
            "",
            "---",
            "",
            "## commit_id 变更明细",
            "",
            "| # | component | system | branch | old_commit_id | new_commit_id |",
            "|---|-----------|--------|--------|---------------|---------------|",
        ]
        for i, d in enumerate(differences, 1):
            branch_str = d["branch"]
            if "old_branch" in d:
                branch_str = f"~~{d['old_branch']}~~ → {d['branch']}"
            lines.append(f"| {i} | `{d['component']}` | {d['system']} | {branch_str} | `{d['old_commit_id']}` | `{d['new_commit_id']}` |")

        branch_changes = [d for d in differences if "old_branch" in d]
        if branch_changes:
            lines.append("")
            lines.append("> 以下组件同时发生了 **branch 变更**：")
            for d in branch_changes:
                lines.append(f"> - `{d['component']}`: ~~{d['old_branch']}~~ → `{d['branch']}`")

    lines += [
        "",
        "---",
        "",
        "## 按 system 分类汇总",
        "",
        "| system | 变更数 | 涉及组件 |",
        "|--------|--------|----------|",
    ]
    for sys_name in sorted(sys_summary.keys(), key=lambda s: (-len(sys_summary[s]), s)):
        comps = sys_summary[sys_name]
        lines.append(f"| `{sys_name}` | {len(comps)} | {', '.join(comps)} |")

    with open(output_path, "w") as f:
        f.write("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="对比两个 app_version.json 中 repos 的 commit_id 差异",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  %(prog)s master-P401273-*      master-P401968-*
  %(prog)s "develop-*0615*"      "develop-*0616*"
  %(prog)s ./old/app_version.json ./new/app_version.json
  %(prog)s                      # 自动发现""",
    )
    parser.add_argument("old", nargs="?", help="旧版本目录/通配符/app_version.json 路径")
    parser.add_argument("new", nargs="?", help="新版本目录/通配符/app_version.json 路径")
    parser.add_argument("-o", "--output-dir", default=".", help="输出目录 (默认: 当前目录)")
    parser.add_argument("--no-md", action="store_true", help="不生成 Markdown 报告")
    parser.add_argument("--no-json", action="store_true", help="不生成 JSON 文件")
    args = parser.parse_args()

    # 确定输入
    if args.old and args.new:
        old_label, old_path = find_json(args.old)
        new_label, new_path = find_json(args.new)
    else:
        print("未指定参数，自动发现当前目录...")
        old_label, old_path, new_label, new_path = auto_discover()

    print(f"\n旧版本: {old_label}")
    print(f"新版本: {new_label}")

    # 加载 JSON
    with open(old_path) as f:
        old_data = json.load(f)
    with open(new_path) as f:
        new_data = json.load(f)

    # 对比
    old_repos, new_repos, differences, added, removed = compare(old_data, new_data)

    # 终端输出
    print(f"\n=== 概要 ===")
    print(f"旧版本 repos 数: {len(old_repos)}")
    print(f"新版本 repos 数: {len(new_repos)}")
    print(f"commit_id 变更:   {len(differences)}")
    print(f"新增:             {len(added)}")
    print(f"移除:             {len(removed)}")

    if differences:
        print(f"\n=== 变更明细 ===")
        for d in differences:
            flag = " [BRANCH也变了]" if "old_branch" in d else ""
            print(f"  {d['component']:38s} system={d['system']:25s} branch={d['branch']}{flag}")
            print(f"    old: {d['old_commit_id']}")
            print(f"    new: {d['new_commit_id']}")

    # 构建 JSON 结果
    result = {
        "old_version": old_label,
        "new_version": new_label,
        "summary": {
            "changed": len(differences),
            "added": len(added),
            "removed": len(removed),
            "total_compared": len(old_repos),
        },
        "differences": differences,
    }
    if added:
        result["added"] = added
    if removed:
        result["removed"] = removed

    # 输出文件
    out_dir = args.output_dir
    os.makedirs(out_dir, exist_ok=True)

    if not args.no_json:
        json_path = os.path.join(out_dir, "version_diff.json")
        with open(json_path, "w") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"\nJSON 已保存: {json_path}")

    if not args.no_md:
        md_path = os.path.join(out_dir, "version_diff.md")
        generate_markdown(old_label, new_label, old_repos, new_repos, differences, added, removed, md_path)
        print(f"Markdown 已保存: {md_path}")


if __name__ == "__main__":
    main()
