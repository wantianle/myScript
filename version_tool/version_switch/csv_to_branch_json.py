#!/usr/bin/env python3
"""功能1: 将CSV表格转换为 mdrive4_branch_YYYYMMDD_HHMMSS.json"""

import csv
import json
import sys
from datetime import datetime
from pathlib import Path


def csv_to_branch_json(csv_path: str, output_dir: str | None = None) -> str:
    csv_path = Path(csv_path)
    if not csv_path.exists():
        print(f"错误: 文件不存在 {csv_path}", file=sys.stderr)
        sys.exit(1)

    result: dict[str, dict[str, str]] = {}
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
            result.setdefault(current_module, {})[component] = branch

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_name = f"mdrive4_branch_{ts}.json"
    out_dir = Path(output_dir) if output_dir else csv_path.parent
    out_path = out_dir / out_name

    with out_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"已生成: {out_path}")
    return str(out_path)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python csv_to_branch_json.py <csv文件路径> [输出目录]")
        print("示例: python csv_to_branch_json.py ../mdrive4/mdrive4_branch_template.csv ../mdrive4/")
        sys.exit(1)
    csv_to_branch_json(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
