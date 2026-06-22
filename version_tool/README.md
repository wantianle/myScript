# compare_versions

对比两个版本的 `app_version.json`，找出 repos 的 `commit_id` 变更、新增和移除，输出终端摘要 + JSON + Markdown 报告。

## 快速上手

```bash
# 1. 把两个版本的目录放在当前目录下（目录里必须有 app_version.json）
ls
# master-P401273-20250615/   master-P401968-20250616/

# 2. 不传参数，自动发现并对比
python3 compare_versions.py

# 3. 查看生成的报告
cat version_diff.md
```

也可以显式指定：

```bash
# 指定两个目录
python3 compare_versions.py master-P401273-0615 master-P401968-0616

# 用通配符（glob）
python3 compare_versions.py "master-P401273-*" "master-P401968-*"

# 直接传 app_version.json 路径
python3 compare_versions.py ./old/app_version.json ./new/app_version.json
```

## 输入

脚本接受**旧版本**和**新版本**两个参数，每个参数可以是：

| 参数形式 | 说明 |
|---------|------|
| 目录名 | 自动拼接 `目录/app_version.json` |
| glob 通配符 | 匹配目录，取第一个含 `app_version.json` 的 |
| `.json` 文件路径 | 直接使用该 JSON 文件 |

不传参数时，**自动发现**当前目录下所有含 `app_version.json` 的目录：

- **恰好 2 个** → 按名字排序，前者为旧，后者为新
- **超过 2 个** → 按分支名（`-P数字` 之前的部分）分组：
  - 同分支 → 取最早和最晚的目录
  - 多分支 → 报错，提示手动指定

## 输出

### 终端

打印概要（总数、变更、新增、移除）和变更明细。

### 文件

默认输出到当前目录：

| 文件 | 内容 |
|------|------|
| `version_diff.json` | 结构化差异数据 |
| `version_diff.md` | 可读的 Markdown 报告（含概要表、变更明细表、按 system 分类汇总） |

可通过 `-o` 指定输出目录，通过 `--no-json` / `--no-md` 关闭对应输出。

## 选项

```
-o, --output-dir DIR   输出目录（默认: 当前目录）
--no-md                不生成 Markdown 报告
--no-json              不生成 JSON 文件
-h, --help             查看帮助
```

## 示例

```bash
# 通配符对比两个 develop 分支构建
python3 compare_versions.py "develop-*0615*" "develop-*0616*"

# 指定输出到 /tmp
python3 compare_versions.py old new -o /tmp

# 只生成 JSON，不要 Markdown
python3 compare_versions.py old new --no-md

# 对比两个不同目录下的文件
python3 compare_versions.py /path/to/v1/app_version.json /path/to/v2/app_version.json
```
