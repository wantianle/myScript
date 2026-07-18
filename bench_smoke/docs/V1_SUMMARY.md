# bench_smoke V1 完成摘要与后续路线图

本文档是对第一版实现的完整总结，同时给出后续维护建议和冒烟测试报告路线图。
面向对象：后续接手维护或扩展的开发/测试同学。

---

## 1. V1 完成摘要

### 1.1 目录结构（最终态）

```
bench_smoke/
├── run.sh                    # CLI 入口（唯一对外命令）
├── settings.sh               # 固定配置（SSH 密码/主机/路径）— run.sh 自动 source
├── datasets.yaml             # 默认数据集清单（6 条真实 bench 数据）
├── README.md                 # 使用说明
├── docs/                     # 设计/审查/路线图文档
│   ├── SPEC.md
│   ├── DESIGN.md
│   ├── REVIEW.md
│   └── V1_SUMMARY.md         # 本文件
├── src/bench_smoke/          # Python 包
│   ├── cli.py                # 命令行解析（run / debug 子命令）
│   ├── orchestrator.py       # 工作流编排（run_batch / run_full / batch_summary）
│   ├── models.py             # 共享数据类型（dataclass / enum）
│   ├── config.py             # 配置加载（默认值 + 环境变量覆盖）
│   ├── manifest.py           # 清单加载与校验
│   ├── command_runner.py     # 命令执行（本地 subprocess + SSH/sudo）
│   ├── step_runner.py        # 步骤包装器
│   ├── result_store.py       # 产物持久化（目录创建 / summary / execution）
│   ├── env.py                # 台架运行时环境辅助（shell_init / mkit_bin）
│   ├── logging_setup.py      # 日志配置
│   ├── steps/                # 步骤模块
│   │   ├── versioning.py     # vmc install + systemctl mdrive 启停
│   │   ├── data_prep.py      # NAS 复制 + 缓存管理
│   │   ├── module_control.py # soc1/soc2 模块启停
│   │   ├── playback.py       # mkit play 回灌
│   │   ├── recorder.py       # supervisor-managed Recorder 启停 + mcap 发现
│   │   └── metadata.py       # vmc list + mkit info 采集
│   └── extensions/           # 扩展点（NAS 上传已实现于 orchestrator，stub 供未来扩展）
├── output/                   # 运行产物（自动创建）
│   ├── runs/                 # 批次运行产物
│   └── cache/                # 数据缓存
└── .gitignore
```

### 1.2 入口方式

```bash
# 全量跑（读 datasets.yaml 默认清单）
./run.sh

# 选特定数据集
./run.sh --dataset-id 7037566695

# 指定自定义清单和版本包
./run.sh run --manifest other.yaml --package mdrive=1.2.3

# 单步排障
./run.sh debug playback --dataset-id 7037566695

# 清理历史 runs 产物（不影响 cache）
./run.sh clean-runs
```

### 1.3 各文件/目录角色

| 文件/目录 | 角色 |
|---|---|
| `run.sh` | 唯一对外入口。自动注入 `PYTHONPATH` 和 `BENCH_SMOKE_RUN_ROOT`，source `settings.sh`，转发到 Python CLI |
| `settings.sh` | 固定配置：SSH 密码、soc1/soc2 IP。可选的路径/超时覆盖项（注释形式） |
| `datasets.yaml` | 默认数据集清单。含 `packages`（版本包）和 `datasets`（6 条，各含 dataset_id / short_name / issue_description / feishu_url / source_path） |
| `output/runs/` | 运行产物。结构见 §1.4 |
| `output/cache/` | 数据缓存。按 `dataset_id` 分目录，`source_manifest.txt` 记录源路径，`data/` 存复制来的原始传感器文件 |
| `src/bench_smoke/` | 全部 Python 源码。`steps/` 下每个文件负责一个独立步骤 |

### 1.4 产物布局（运行态）

```
output/
├── runs/
│   └── <YYYYMMDD_HHMM>/                     # 批次目录（年月日_时分）
│       ├── batch_summary.txt           # 批次级总览（始终生成，含 install/module_switch 状态）
│       ├── batch_summary.json          # 批次级结构化（始终生成）
│       └── <dataset_id>__<short_name>/ # 单 dataset 产物目录
│           ├── summary.txt             # 终端可读单条结果
│           ├── summary.json            # 机器可读完整结构
│           ├── run_context.json        # 运行上下文快照
│           ├── run.log                 # 运行日志
│           ├── execution.json          # 步骤明细（仅失败/debug 时）
│           └── playback_<dataset_id>_<YYYYMMDD_HHMM>.mcap  # 主输出 mcap
└── cache/
    └── <dataset_id>/
        ├── source_manifest.txt
        └── data/
            └── <原始输入文件>
```

结合一个实际示例（2026-07-06 14:30 执行 2 条数据集）:

```
output/runs/20260706_1430/
  batch_summary.txt
  batch_summary.json
  7037566695__鬼探头二轮车/
    summary.txt, summary.json, run_context.json, run.log
    playback_7037566695_20260706_1430.mcap
  7037600648__掉头碰撞风险/
    summary.txt, summary.json, run_context.json, run.log
    playback_7037600648_20260706_1430.mcap
```

### 1.5 当前已实现的能力

**管线**:

*批次级（每批仅一次）:*
1. `install_packages` — 停止 soc1/soc2 mdrive → soc1 上 `vmc install -n <pkg> -v <ver>` → 重启 soc1/soc2 mdrive
2. `switch_modules` — 关闭生产模块，启动 debug 模块（soc1/soc2 分别处理）

*per-dataset（每条 dataset 依次）:*
3. `prepare_data` — NAS 挂载检查 → 缓存命中/未命中 → 复制到本地 `cache/<dataset_id>/data/`
4. `start_recorder` — 通过 supervisorctl 启动 Recorder 服务
5. `playback` — 后台启动 `mkit play`（子进程），紧跟 recorder 之后
6. `stop_recorder` — 等待回灌完成后停止 Recorder → discover 新生成的 mcap 文件
7. `collect_metadata` — 采集 `vmc list` 和 `mkit info` 信息
8. `summarize` — 按文件大小选择主 mcap → move 到 run_dir → 清理 recorder 原始目录 → 写 summary

**数据管理**:
- 缓存去 hash：按 `dataset_id` 缓存，`source_manifest.txt` 防源路径漂移
- 主 mcap 选择：按文件大小取最大者（避免小尾段被误认为主文件）
- 主 mcap move + 清理：成功后 move 主文件到 run_dir，`sudo rm -rf` 清空原始 recorder 输出目录

**批次支持**:
- `run_batch` 统一处理 1 条或多条 dataset，遇首个失败即停止
- 所有 dataset 共享同一个 `YYYYMMDD_HHMM` 批次目录
- 始终生成 `batch_summary.txt` + `batch_summary.json`
- install_packages 与 switch_modules 在批次级仅执行一次
- 完成时自动通过 sudo 非交互方式上传批次目录到 NAS（目标已存在则跳过）

**容错**:
- fail-fast：任何步骤失败即停止后续
- recorder 已启动时若后续步骤失败，自动 best-effort 清理
- main 级别 try/except，保证异常有迹可循

**配置**:
- 内建默认值覆盖全部关键路径/端口/超时（无需配置文件即可运行）
- 8 个环境变量支持覆盖：`SSH_PASSWORD` / `SOC1_HOST` / `SOC2_HOST` / `RUN_ROOT` / `RECORD_ROOT` / `MOUNT_CHECK_PATH` / `COMMAND_TIMEOUT_SEC` / `PLAYBACK_TOPICS`
- `settings.sh` 提供一键配置入口

---

## 2. 冒烟测试报告路线图

### 2.1 什么时候可以产出"冒烟测试报告"

当前工具已经可以**运行并产出结构化数据**，但尚缺最后一步：将这些数据转化为人类可直接阅读的"冒烟测试报告"。产出一份合格报告所需的全部基础数据已就绪（§4.1），只是缺少一个渲染层。

### 2.2 先做什么、后做什么

| 阶段 | 内容 | 说明 |
|---|---|---|
| **已完成 (V1.0)** | 管线、数据、产物结构、NAS 上传 | 可以稳定运行，产出 json/txt，自动推送 NAS |
| **下一步 (V1.1)** | 批处理脚本 + cron 调度 | 让工具真正变成"每日自动跑" |
| **再下一步 (V1.2)** | 简易文本报告（聚合版） | 把所有 dataset 的 summary.txt 拼成一个"今日冒烟报告.txt" |
| **再下一步 (V1.2)** | 中文终端彩色输出 | `./run.sh` 结束时打印直观的 PASS/FAIL 面板 |
| **然后 (V2.0)** | 静态 HTML 报告 | 单文件，可直接浏览器打开，无需服务端 |

### 2.3 为什么当前先不直接做 HTML

1. **当前台架没有浏览器** — HTML 在台架上无法直接查看；需要先把产物传输到开发机再打开，没有本质便利
2. **基础不稳时做 HTML 是浪费** — 管线跑通之前，HTML 模板反复改不如直接看 txt/json
3. **txt/json 已经足够定位问题** — `batch_summary.txt` 一眼就能看到哪条 dataset 挂了、挂在哪一步；`summary.txt` 有完整步骤用时和信息
4. **HTML 需要额外依赖** — 即使用 Jinja2 也要引入新的包依赖；做纯静态 HTML 则需要模板字符串管理，增加代码复杂度

综上：HTML 报告是有价值的目标，但应该在"管线稳定运行数天、数据积累够多"之后再投入。

---

## 3. 后续维护方式建议

### 3.1 是否需要继续整理问题单

建议**继续**。当前 `datasets.yaml` 中的 6 条数据集全部来自飞书 issue。维护方式：

- 每发现一个新的冒烟问题（算法回灌后行为异常），就在飞书建 issue
- 把 issue ID 作为 `dataset_id`，提取对应 bag 路径填入 `datasets.yaml`
- 不需要在工具内维护额外的问题单数据库

### 3.2 是否按问题分类维护多份 dataset 清单/批次

当前规模（6 条）不需要分文件。当增长到 20+ 条时建议拆分为：

```
datasets/
  daily.yaml          # 日常快速冒烟（~10 条核心场景）
  weekly.yaml         # 周回归（全部场景）
  ghost_rider.yaml    # 按问题类型分类（可选）
```

**批次执行建议**:
- `./run.sh run --manifest datasets/daily.yaml` — 每日 CI 跑
- `./run.sh run --manifest datasets/weekly.yaml` — 手动/定时周跑
- 分文件的好处：不同频率跑不同子集，减少单次运行时间

### 3.3 bench 执行如何组织更合理

| 场景 | 建议 |
|---|---|
| 每日自动 | cron job: `cd /home/nvidia/bench_smoke && ./run.sh` + 产物自动推送到 NAS/开发机 |
| 手动按需 | `./run.sh --dataset-id <issue_id>` 单条调试 |
| 版本升级验证 | 替换 `datasets.yaml` 中 packages 版本号，全量跑一次 → 看 batch_summary |
| 问题复现 | `./run.sh debug <step>` 单步执行，用 `--run-id` 重入已有上下文 |

建议在台架上增加一个简单的 cron wrapper 脚本：

```bash
#!/bin/bash
# /home/nvidia/daily_bench.sh
cd /home/nvidia/bench_smoke
./run.sh 2>&1 | tee -a logs/daily_$(date +%Y%m%d).log
# NAS 上传已由 run_batch 自动处理，无需额外 rsync
```

---

## 4. 生成 HTML 需要的基础

### 4.1 当前已有的基础数据

| 数据源 | 内容 |
|---|---|
| `batch_summary.json` | 批次级：total/success/failed，每条 dataset 的 id/name/status/failed_step |
| `summary.json`（每 dataset） | 详细：run_id、steps 列表（含每条命令的 stdout/stderr/duration）、packages、generated_mcaps |
| `execution.json`（每 dataset，失败时） | 步骤执行明细（含 error_type），比 summary.json 的 steps 更细 |
| `datasets.yaml` | 静态信息：short_name、issue_description、feishu_url |
| `playback_*.mcap` | 主输出包，可直接用于后续算法验证 |

这些足以生成一份包含以下内容的 HTML 报告：

- 批次总览（PASS/FAIL 数量，按颜色标记）
- 每条 dataset 的详细展开（步骤用时、失败原因、MCAP 路径）
- 飞书 issue 链接（可点击跳转）

### 4.2 还缺什么元信息或约束

| 缺项 | 影响 | 优先级 |
|---|---|---|
| **版本包的 commit hash / build 号** | 报告中无法显示"本次验证的版本是哪个 commit" | 高 |
| **台架硬件信息**（soc1/soc2 型号、驱动版本） | 无法区分不同台架的差异 | 中 |
| **运行环境快照**（`vmc list` 输出结构化） | 目前 `vmc list` 只有原始文本，未解析 | 低 |
| **MCAP 元信息**（时长、topic 数、帧数） | `mkit info` 已有输出，但未提取到 JSON | 低 |

建议的补救方式：
- **版本 commit hash**：在 `install_versions` 步骤中增加一条 `md version` 命令，将输出写入 `version_info.txt`；或在 summary.json 中增加 `package_versions` 字段
- **台架信息**：在 `collect_metadata` 步骤中增加 `uname -a` / `cat /proc/device-tree/model`，写入 run_context.json

### 4.3 最小 HTML 版本 vs 完整 HTML 版本

**最小版本（推荐先做）**:
- 单个静态 HTML 文件，无外部依赖（CSS/JS 内联）
- 从 `batch_summary.json` + 各 dataset 的 `summary.json` 读取数据
- 页面结构：
  - 标题栏：批次时间、Total/Success/Failed 计数
  - 每条 dataset 一行：状态图标（✅/❌）、ID、short_name、失败步骤
  - 点击展开：步骤列表、用时、MCAP 路径、飞书链接
- 生成方式：Python 脚本在 `run_batch` 结束时调用，写到批次根目录下 `report.html`
- 依赖：零（用 Python 字符串拼接 HTML，或用 `html` 标准库）

**完整版本（后续迭代）**:
- 多页面或 tab 切换：批次总览 / 历史趋势 / 单条详情
- 图表：按日期的 PASS/FAIL 趋势、步骤耗时分布
- 历史数据查询：扫描 `output/runs/` 下所有历史批次
- MCAP 内嵌播放器（如有需要）
- 可能的依赖：Jinja2（模板）、Chart.js（图表，CDN 加载即可）

---

## 5. 面向当前个人台架使用场景的下一阶段推荐

按优先级排序，推荐接下来先做这 4 件事：

### 1. 每日自动调度（cron + 日志）
> 让工具真正变成"每日冒烟"，而不是"手动跑才冒烟"。
- 写一个简单的 cron wrapper 脚本
- 每天定时跑一次，输出到带日期的日志文件
- 失败时发 notify（飞书 webhook 或简单 echo）

### 2. 产物自动上传到 NAS ✓ (已实现)
> `run_batch` 完成时自动通过 sudo 非交互上传批次目录到 `/media/nas/mdrive4/bench_smoke_test/`。目标已存在时跳过不覆盖。

### 3. 补充版本信息到 summary.json
> 为 HTML 报告铺路，也让当前 txt 报告更有用。
- 在 `install_versions` 中增加 `md version` 输出，解析后写入 `run_context.json`
- summary.txt 中额外显示版本号

### 4. 简易文本报告聚合
> 不等 HTML，先用纯文本把所有 dataset 结果拼一起。
- `./run.sh` 全部跑完后，在终端打印一个"今日结果面板"
- 或者额外生成一个 `report.txt` 放在批次根目录下，内容是各 dataset summary.txt 的精简拼接

### 暂时不做但值得记下的
- HTML 报告（基础数据已就绪，等管线稳定 1-2 周后再做）
- 历史趋势图表（需要积累至少 2 周以上的数据）
- 多台架并行执行（当前单台架单 soc2 够用）
- 飞书 bot 自动通知失败（等 cron 稳定后再加）
