# mdrive4 版本分支管理

## 文件结构

```
config/
├── mdrive4/
│   ├── mdrive4_branch_template.csv   ← 版本管理总表（WPS/Excel 编辑）
│   └── *_modules.json                ← 各模块 CI 配置（脚本回写目标）
└── scripts/
    ├── apply_branch_json.py           ← CSV → 直接更新各模块 JSON
    └── README.md
```

## 工作流

```
飞书表格更新  →  导出 CSV  →  一键回写各模块
```

### 1. 飞书更新并导出 CSV

在飞书版本管理表格中修改 `branch` 列，完成后导出为 CSV，替换 `mdrive4/mdrive4_branch_template.csv`。

| 列 | 说明 | 示例 |
|---|---|---|
| `module` | 模块组名（仅首行填写） | `avm` |
| `component` | 组件名 | `hmiproxy` |
| `branch` | 目标分支 | `mdrive4` |
| `branch_description` | 改分支原因（可选） | `临时切测试分支` |
| `component_description` | 组件说明 | `AVM HMI代理` |

### 2. 一键回写

```bash
python scripts/apply_branch_json.py mdrive4/mdrive4_branch_template.csv
```

脚本自动完成：
- 解析 CSV（支持合并单元格、多行文本）
- 按 `{模块组}_modules.json` 匹配文件
- 逐组件更新 `branch` 字段
- 打印更新日志和未匹配警告
- 未在 CSV 中的组件不受影响

### 完整示例

```bash
# teleop 切测试分支做 CI
# 1. 飞书表格里 teleop 的 branch 改为 test_ci，导出 CSV 覆盖 mdrive4_branch_template.csv
# 2. 回写
python scripts/apply_branch_json.py mdrive4/mdrive4_branch_template.csv
# 3. 提交
git add .
git commit -m "chore: teleop 切 test_ci 分支"
git push
```

## 新增模块

新增 `planning_modules.json` 后，CSV 中添加 `planning` 模块组即可，脚本自动兼容。
