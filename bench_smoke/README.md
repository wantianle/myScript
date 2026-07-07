# bench_smoke —— Orin 域控台架每日开环冒烟测试

一套运行在 Orin 域控台架上的自动化每日冒烟测试工具。
整体 scp 到台架后，进入目录执行 `./run.sh` 即可使用。

---

## 快速开始

```bash
# 1. 部署到台架（soc2）
scp -r bench_smoke/ nvidia@192.168.10.3:/home/nvidia/bench_smoke/

# 2. 进入工具目录
cd /home/nvidia/bench_smoke

# 3. 设置密码（编辑 settings.sh 或 export 环境变量）
export BENCH_SMOKE_SSH_PASSWORD='your-password'

# 4. 运行（无参默认全流程，使用内置 datasets.yaml）
./run.sh

# 选特定数据集
./run.sh --dataset-id 7037566695
./run.sh --dataset-id 7037566695,7037600648
./run.sh --dataset-id 7037566695 --dataset-id 7037600648

# 命令行覆盖 packages
./run.sh --package mdrive=1.2.3

# 单步排障
./run.sh debug playback
./run.sh debug playback --dataset-id 7037566695

# 清理历史 runs 产物（不影响 cache）
./run.sh clean-runs
```

---

## 功能概述

1. **安装版本** — 批次级，仅执行一次：停止 soc1/soc2 mdrive → `vmc install -n <pkg> -v <version>` → 重启 mdrive。全部已安装则跳过。
2. **准备数据** — 从 NAS 复制原始传感器数据到本地缓存目录。同源只复制一次。
3. **切换模块** — 批次级，仅执行一次：关闭生产模块，启动 debug 模块（soc1/soc2 分别处理）。
4. **录制 + 回灌** — 先启动 Recorder，再后台启动 `mkit play`，重叠执行。
5. **停止录制** — 等待回灌完成后停止 Recorder。
6. **mcap 后处理** — 成功时按文件大小选取主 mcap，move 到 run 目录并重命名，清理原始 recorder 输出目录。
7. **采集元数据** — 执行 `vmc list` 和 `mkit info`。
8. **生成汇总** — 每条 dataset: `summary.json` + `summary.txt`；批次级: `batch_summary.json` + `batch_summary.txt`（始终生成）。
9. **上传到 NAS** — 每次批处理完成后（不论 1 条或多条），通过 sudo 非交互方式将本次批次目录上传到 `/media/nas/mdrive4/bench_smoke_test/`（NAS 上 dataset 子目录仅保留 dataset_id，去掉 `__short_name` 避免中文乱码；NAS 未挂载或上传失败时仅 warning，不丢失本地结果）。

---

## 目录结构

```
bench_smoke/
├── run.sh                    # CLI 入口（唯一对外命令）
├── settings.sh               # 固定配置（SSH/路径/超时，run.sh 自动 source）
├── datasets.yaml             # 默认数据集清单（含 6 条真实 bench 数据）
├── README.md
├── docs/                     # 研发文档（SPEC/DESIGN/REVIEW + V1_SUMMARY）
├── output/                   # 运行产物根目录（自动创建）
│   ├── runs/                 # 批次运行产物
│   └── cache/                # 数据缓存
└── src/
    └── bench_smoke/          # Python 包
        ├── cli.py            # 命令行解析
        ├── orchestrator.py   # 工作流编排
        ├── models.py         # 共享数据类型
        ├── config.py         # 配置加载
        ├── manifest.py       # 清单加载
        ├── command_runner.py # 命令执行
        ├── step_runner.py    # 步骤包装器
        ├── result_store.py   # 产物持久化
        ├── logging_setup.py  # 日志配置
        ├── steps/            # 步骤模块
        │   ├── versioning.py
        │   ├── data_prep.py
        │   ├── module_control.py
        │   ├── playback.py
        │   ├── recorder.py
        │   └── metadata.py
        └── extensions/       # 扩展点 stubs
```

---

## 数据集清单

`datasets.yaml` 为默认清单，`./run.sh` 无参时自动使用。

```yaml
packages:
  - mdrive=1.2.3       # 核心代码库
  - mdrive_conf=1.2.3  # 核心配置库
  - mdrive_map=1.2.3   # 地图库（只有此包追加 --deps）

datasets:
  - dataset_id: "7037566695"
    short_name: "鬼探头二轮车"
    issue_description: "鬼探头二轮车"
    feishu_url: "https://project.feishu.cn/t03o4q/issue/detail/7037566695"
    source_path: "/media/nas/mdrive4/.../record.00050.144153.mcap"
```

**dataset 字段说明**:
- `dataset_id`: 唯一标识（飞书 issue ID），用于产物目录和命令行筛选
- `short_name`: 简短可读名，用于产物目录；缺失时回退为 dataset_id
- `issue_description`: 问题描述（人类可读，用于 summary.txt）
- `feishu_url`: 飞书 issue 链接（用于 summary.txt）
- `source_path`: NAS 上的原始数据路径（绝对路径）

**dataset 选择规则**:
- 不写 `--dataset-id` → 跑全部
- 写 `--dataset-id` → 支持单个、多次、逗号分隔；去重后按清单原顺序

---

## 环境变量

通过 `settings.sh` 或直接 export 覆盖默认值。所有变量均有内建默认值，只需设置与默认不同的项。

| 变量 | 作用 | 默认值 |
|---|---|---|
| `BENCH_SMOKE_SSH_PASSWORD` | SSH 密码 | - |
| `BENCH_SMOKE_SOC1_HOST` | soc1 地址 | `192.168.10.2` |
| `BENCH_SMOKE_SOC2_HOST` | soc2 地址 | `localhost` |
| `BENCH_SMOKE_RUN_ROOT` | 产物根目录 | `<tool_root>/output` |
| `BENCH_SMOKE_RECORD_ROOT` | Recorder 原始落盘路径 | `/mdrive_data/bag` |
| `BENCH_SMOKE_MOUNT_CHECK_PATH` | NAS 挂载检查路径 | `/media/nas` |
| `BENCH_SMOKE_COMMAND_TIMEOUT_SEC` | 单条命令超时（秒） | `30` |
| `BENCH_SMOKE_PLAYBACK_TOPICS` | 回灌 topic 列表（逗号分隔） | 内置默认 21 个 topic |

**修改回灌 topic**: 如果后续回灌 topic 有变化，优先修改 `settings.sh` 中的 `BENCH_SMOKE_PLAYBACK_TOPICS`，无需改动 Python 代码。格式为逗号分隔的 topic 列表，例如：

```bash
export BENCH_SMOKE_PLAYBACK_TOPICS="/sensor/gnss/raw,/sensor/imu,camera1,camera2"
```

不设置此变量时，回灌 topic 使用内置默认值（共 21 个 topic，覆盖 GNSS/IMU/LiDAR/Camera/Vehicle 等传感器）。

其中 `run_root` 由 `run.sh` 按当前工具目录自动注入为：

```text
<tool_root>/output
```

产物子目录 `runs/` 和 `cache/` 由工具在 run_root 下自动创建。
因此无论工具整体放在 `/mdrive_data/bench_smoke` 还是 `~/bench_smoke`，
默认产物都会跟着工具目录走，不再依赖外部硬编码路径。

---

## 产物布局

一次 `./run.sh` 产生的所有产物位于同一个批次目录下。

```
output/
├── runs/
│   └── <YYYYMMDD_HHMM>/                     # 批次目录 (年月日_时分)
│       ├── batch_summary.txt           # 批次级人可读汇总（始终生成）
│       ├── batch_summary.json          # 批次级结构化汇总（始终生成）
│       ├── <dataset_id>__<short_name>/ # 单 dataset 产物目录
│       │   ├── summary.txt             # 终端可读汇总
│       │   ├── summary.json            # 机器可读汇总
│       │   ├── run_context.json        # 运行上下文快照
│       │   ├── run.log                 # 运行日志
│       │   ├── execution.json          # 步骤明细（仅失败/debug 时）
│       │   └── playback_<dataset_id>_<YYYYMMDD_HHMM>.mcap  # 主输出 mcap
│       └── ...
└── cache/
    └── <dataset_id>/                   # 数据缓存（按 dataset_id）
        ├── source_manifest.txt         # 记录缓存的 source_path
        └── data/                       # 原始传感器数据
```

**示例**（2026-07-06 14:30 执行 2 条数据集）:
```
output/
  runs/
    20260706_1430/
      batch_summary.txt
      batch_summary.json
      7037566695__鬼探头二轮车/
        summary.txt
        summary.json
        run_context.json
        playback_7037566695_20260706_1430.mcap
      7037600648__掉头碰撞风险/
        summary.txt
        summary.json
        run_context.json
        playback_7037600648_20260706_1430.mcap
  cache/
    7037566695/
      source_manifest.txt
      data/
        record.00050.144153.mcap
```

**产物规则**:
- **成功 run**: summary.json、summary.txt、run.log、run_context.json、playback_*.mcap
- **失败 run**: 额外包含 execution.json
- **debug**: 额外包含 execution.json
- **同一分钟重复运行**: 批次目录追加 `_2`、`_3` 后缀（如 `20260706_1430_2`）
- **short_name 回退**: 若 dataset 未提供 short_name，使用 dataset_id 替代
- **单 dataset 运行**: 也生成 batch_summary.txt/json 于批次目录根下（统一批处理语义）
- **多 dataset 批次**: 同样生成 batch_summary.txt + batch_summary.json 于批次目录根下

**产物文件角色**:
| 文件 | 格式 | 层级 | 作用 |
|---|---|---|---|
| `summary.txt` | 纯文本 | 单 dataset | 终端可读单条结果：Run ID / Status / Steps / MCAPs |
| `summary.json` | JSON | 单 dataset | 机器可读完整结构，供 HTML/后续自动处理消费 |
| `batch_summary.txt` | 纯文本 | 批次 | 人眼一扫：Total / Success / Failed，每条一行 |
| `batch_summary.json` | JSON | 批次 | 结构化批次视图，供 HTML/自动报告消费 |
| `execution.json` | JSON | 单 dataset | 步骤执行明细（仅失败/debug 时）— **只有 JSON 版** |
| `run_context.json` | JSON | 单 dataset | 运行上下文快照（dataset、packages、路径等） |

注意：Recorder 原始 `.mcap` 仍会先写到系统级 `record_root`（默认 `/mdrive_data/bag`），
随后工具会把主输出整理到本次运行目录中，因此日常使用只需要关注 `output/` 下的产物。

---

## 批次汇总（batch_summary）

当一次运行包含 1 条或多条数据集时，批次目录根下都会生成 batch_summary：

- **`batch_summary.txt`** — 终端可读批次总览，包含 Total/Success/Failed 计数和每条 dataset 一行结果
- **`batch_summary.json`** — 结构化批次视图，供后续 HTML 渲染或自动报告消费

---

## 常见排查

- **挂载/NAS**: `mountpoint -q /media/nas`
- **supervisor/Recorder**: `sudo supervisorctl status`；失败时自动采集 `journalctl`
- **run 失败**: 先看 `summary.txt`，再看 `run.log`
- **维护与扩展**: 见 [docs/V1_SUMMARY.md](docs/V1_SUMMARY.md) — 含路线图、HTML 报告规划、后续维护建议

---

## 退出码

| 码 | 含义 |
|---|---|
| 0 | 成功 |
| 1 | 工作流或步骤失败 |
| 2 | CLI、配置或清单错误 |
