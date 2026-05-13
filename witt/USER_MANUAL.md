# Witt 用户手册

本文面向日常使用者和一线排查人员，说明 Witt 的功能、执行链路、目录产物和关键字段。内部模块边界和开发约束见 [ARCHITECTURE.md](/home/mini/dev/myScript/witt/ARCHITECTURE.md)。

## 1. 工具定位

Witt 是一个面向 Cyber Record 数据的终端工具，主要解决以下场景：

- 查询本地、NAS 或车端数据中的 tag 与 record。
- 按 tag 前后时间窗切片，生成可回播的 `.split` 文件。
- 直接回播原始 record，不落切片结果。
- 扫描本地切片目录并选择 SOC 回播。
- 手动拖拽 record 文件或目录回播。
- 支持标准回播和红绿灯回灌回播。
- 保存回播历史，回播结束后生成 issue 草稿。

## 2. 启动方式

优先使用项目虚拟环境：

```bash
.venv/bin/python main.py
```

如果依赖已经安装到系统 Python，也可以执行：

```bash
python3 main.py
```

首次启动会把仓库模板 [config/settings.yaml](/home/mini/dev/myScript/witt/config/settings.yaml) 复制到 `~/.witt/settings.yaml`。后续运行默认读取 `~/.witt/settings.yaml`。

## 3. 前置条件

- Python 兼容 3.8。
- Docker 容器已存在，默认容器名来自 `docker.container`。
- 容器内可执行 `cyber_recorder info`、`cyber_recorder split`、`cyber_recorder play`。
- 本地回播路径应位于 `docker.host_mount` 下，默认是 `/media`，否则无法映射到容器路径。
- 如使用车端模式，需要 SSH 能连接 `remote.user@remote.ip`，且车端环境能执行 `cyber_recorder`。
- 切片源 record 所在目录需要存在 `version*` 文件；否则对应批次会被跳过。
- 回播环境恢复依赖 `host.mdrive_root/vmc.sh` 和 version 文件中的 mdrive 版本字段。

## 4. REPL 命令

启动后进入 `Witt >` 命令行。

| 命令 | 别名 | 功能 |
| --- | --- | --- |
| `help` | `h`, `?` | 查看命令帮助，支持 `help <command>`。 |
| `config` | `cfg` | 打开 `~/.witt/settings.yaml`，编辑结束后重建当前会话配置。 |
| `slice` | `s` | 查询 record、选择 tag、切片，并可选择立即回播。 |
| `replay` | `r` | 查询后直接回播原始 record，不生成切片目录。 |
| `scan` | `a` | 扫描本地回放目录，从回播库选择条目回播。 |
| `manual` | `m` | 手动粘贴或拖拽 record 文件/目录回播。 |
| `history` | `his` | 浏览历史并选择回播。 |
| `history last` | - | 直接回播最新一条历史。 |
| `history <序号>` | - | 按展示序号回播历史。 |
| `history clear` | - | 清空全部回播历史。 |
| `traffic` | `tl` | 红绿灯回灌模式，支持自动扫描或手动文件。 |
| `env` | `e` | 查看当前车号、日期、模式、工作目录、日志目录等摘要。 |
| `clear` | `cls` | 清屏并重新展示 banner。 |
| `quit` | `q`, `exit` | 退出工具。 |

## 5. 通用输入规则

列表选择支持以下表达式：

| 输入 | 含义 |
| --- | --- |
| `1` | 选择第 1 项。 |
| `1,3,5` | 选择第 1、3、5 项。 |
| `2-6` | 选择第 2 到 6 项。 |
| `0` | 全选。 |
| `0 5 7-15` | 反选，表示全选后排除第 5 项和第 7 到 15 项。 |
| `/关键字` | 按关键字筛选当前列表。 |
| `/` | 清空筛选。 |
| 回车 | 返回或取消当前选择。 |

回播时间范围输入规则：

| 输入 | 含义 |
| --- | --- |
| 回车 | 全量播放。 |
| `5` | 从第 5 秒开始播放到结束。 |
| `5-10` | 只播放第 5 秒到第 10 秒。 |

播放倍速支持 `0.1` 到 `10`，常用值是 `0.5`、`1.0`、`2.0`、`5.0`。

## 6. 配置文件字段

用户配置文件路径是 `~/.witt/settings.yaml`。执行 `config` 会用编辑器打开该文件，编辑器退出后 Witt 会尝试重新加载配置。

### 6.1 `remote`

| 字段 | 含义 |
| --- | --- |
| `remote.user` | 车端 SSH 用户名。 |
| `remote.ip` | 车端 IP。 |
| `remote.data_root` | 车端 record/tag 查询根目录。 |

### 6.2 `host`

| 字段 | 含义 |
| --- | --- |
| `host.mdrive_root` | 宿主机 MDrive 工程根目录，环境恢复会读写其中的 `vmc.sh`。 |
| `host.nas_root` | NAS 原始数据根目录。NAS 模式会查找 `<nas_root>/<日期>/<车号>`。 |
| `host.data_root` | 本地原始数据根目录。本地模式查询从这里开始。 |
| `host.dest_root` | 切片导出根目录，也是自动扫描回播的根目录。 |

### 6.3 `docker`

| 字段 | 含义 |
| --- | --- |
| `docker.container` | 执行回播、切片、record 信息解析的 Docker 容器名。 |
| `docker.host_mount` | 宿主机挂载根目录，默认 `/media`。 |
| `docker.docker_mount` | 容器内对应挂载根目录，默认 `/media`。 |
| `docker.docker_scripts` | Docker 环境脚本目录，作为仓库脚本不存在时的回退路径。 |
| `docker.setup_env` | 容器或车端执行 `cyber_recorder` 前 source 的环境脚本。 |

### 6.4 `logic`

| 字段 | 含义 |
| --- | --- |
| `logic.vehicle` | 车辆号，只接受 `XZB6`、`XZT5`、`XZA0` 开头并跟 5 位数字。 |
| `logic.target_date` | 数据日期，运行时默认会初始化为当天，交互中可修改。 |
| `logic.mode` | 数据输入模式：`1` 本地，`2` NAS，`3` 车端。 |
| `logic.version` | 当前回播环境恢复使用的 version 文件路径。自动回播会优先从 record 目录旁查找 `version*`。 |
| `logic.soc` | 查询时的 SOC 路径过滤关键字，默认 `soc` 可同时命中 `soc1`、`soc2`。 |
| `logic.before` | tag 前窗口秒数。切片时表示 tag 前切片秒数，原始回播时表示 tag 前回播秒数。 |
| `logic.after` | tag 后窗口秒数。`before + after` 必须大于 0。 |
| `logic.blacklist` | 切片阶段过滤掉的 channel 列表，会转成 `cyber_recorder split -k` 参数。 |

### 6.5 `paths`

| 字段 | 含义 |
| --- | --- |
| `paths.scripts_dir` | 仓库内辅助脚本目录，默认 `./scripts`。 |

## 7. 工作目录规则

Witt 的会话工作目录由以下字段决定：

```text
<host.dest_root>/<logic.target_date>/<logic.vehicle>
```

例如：

```text
/media/road_test/20260513/XZB600007
```

主要产物如下：

```text
<work_dir>/
  01.20260513_101530/
    meta.json
    soc1/
      20260513101450.record.00001.101450.split
      version.json
    soc2/
      20260513101450.record.00001.101450.split
      version.json
  .witt/
    log/
      witt_20260513_102000.log
    local_library.json
  issues/
    issue_20260513_101530.md
```

说明：

- `01.20260513_101530` 中的 `01` 是查询结果序号，后半段来自 tag 时间。
- 每个 SOC 有独立目录。
- `meta.json` 位于 tag 目录下，用于自动扫描回播。
- `.witt/local_library.json` 是自动回播库缓存。
- `.witt/log` 保存当前日期和车辆下的运行日志。
- `issues` 保存回播结束后生成的 issue 草稿。

## 8. 核心功能链路

### 8.1 `slice`：查询、切片、可选回播

链路：

```text
输入日期和车号
  -> 选择数据源模式
  -> 输入导出路径
  -> 输入 before/after 切片窗口
  -> 查询 tag 和 record
  -> 选择 tag
  -> 可选 channel 过滤
  -> 规划切片批次
  -> 执行 cyber_recorder split
  -> 同步 version 文件
  -> 写入 meta.json
  -> 可选立即进入自动回播
```

数据源模式：

- 本地模式：扫描 `host.data_root`。
- NAS 模式：扫描 `host.nas_root/<日期>/<车号>`。
- 车端模式：通过 SSH 扫描 `remote.data_root`，切片后把远端 `.split` 拉回本地。

切片命令会根据窗口生成：

```text
tag_time - before 作为开始时间
tag_time + after 作为结束时间
```

如果选择了 channel 过滤，过滤项会作为 `-k <channel>` 传给 `cyber_recorder split`。

### 8.2 `replay`：原始数据回播

链路：

```text
输入日期和车号
  -> 选择本地或 NAS 数据源
  -> 输入 before/after 回播窗口
  -> 查询 tag 和 record
  -> 选择一个 tag
  -> 基于原始 record 构造回播列表
  -> 进入标准回播链路
```

该模式不生成导出目录、不写入 `meta.json`，适合只想快速确认原始数据的场景。当前入口不允许选择车端模式。

### 8.3 `scan`：自动扫描本地回播库

链路：

```text
输入日期和车号
  -> 输入要扫描的回播路径
  -> 扫描 <work_dir> 下所有 meta.json
  -> 生成或读取 .witt/local_library.json
  -> 选择 tag
  -> 选择 SOC 或 All
  -> 进入标准回播链路
```

当工作目录没有变化时，会命中本地回播库缓存，减少重复扫描。

### 8.4 `manual`：手动回播

链路：

```text
输入日期和车号
  -> 粘贴或拖拽 record 文件/目录
  -> 递归收集文件名包含 .record 的文件
  -> 读取首尾 record 的 begin/end
  -> 按 record 序号排序
  -> 进入标准回播链路
```

该模式适合临时回放一组散落文件。输入 `q` 返回。

### 8.5 `traffic`：红绿灯回灌

链路：

```text
选择手动文件或自动扫描
  -> 准备回播记录
  -> 选择需要过滤的 channel
  -> 恢复运行环境
  -> 可选启动标准回播栈
  -> 可选启动红绿灯回灌栈
  -> 执行 cyber_recorder play
```

红绿灯回灌会额外启动 Debug_Driver-Camera、Perception-TrafficLight 等节点，并会尝试开启红绿灯配置中的 debug 图保存。

### 8.6 `history`：历史回播

每次成功构造回播命令并执行前，Witt 会保存一条历史记录到：

```text
~/.witt/replay_history.json
```

可用方式：

- `history`：浏览历史并交互选择。
- `history last`：回播最新一条。
- `history <序号>`：回播指定序号。
- `history clear`：清空历史。

历史回播会复用当时的 record 列表、播放范围、倍速和 channel 过滤；如果文件已经不存在，会提示重新选择或清理历史。

## 9. 回播执行链路

所有回播模式最终都会进入同一条回播链路：

```text
准备 ReplayRecord 列表
  -> 输入播放范围和倍速
  -> 生成 cyber_recorder play 命令
  -> 首轮回播前恢复运行环境
  -> 可选启动 Dreamview / Multiviz / 红绿灯节点
  -> 在 Docker 容器内交互执行回播命令
  -> 可继续调整时间范围和倍速
  -> 结束后可记录问题时间点
  -> 生成 issue 草稿
```

回播命令包含以下核心参数：

| 参数 | 来源 |
| --- | --- |
| `-f` | 选择的 record 或 `.split` 文件列表，宿主机路径会映射成容器路径。 |
| `-r` | 播放倍速。 |
| `-k` | channel 过滤列表，仅在用户选择过滤时出现。 |
| `-b` | 回播开始绝对时间。 |
| `-e` | 回播结束绝对时间。 |

环境恢复规则：

- 自动扫描或切片回播会优先从 record 目录旁查找 `version*` 文件。
- 找不到 version 文件时，会提示用户拖拽或粘贴 version 文件路径。
- version 文件会解析 `mdrive`、`mdrive_conf`、`mdrive_model`、`mdrive_map`、`mdrive_map_localization` 等字段。
- 如果 `host.mdrive_root/vmc.sh` 中版本或车号需要更新，会重写对应变量并执行 `vmc.sh`。

标准回播栈会尝试启动 Supervisor、Dreamview、Debug_Driver-LiDAR 和 Multiviz，并打开 `http://localhost:8888`。

## 10. 查询匹配规则

查询过程会先扫描候选文件，再解析 tag 文件。

record 候选条件：

- 文件名以 `logic.target_date` 开头。
- 文件名包含 `record`。
- 如果 `logic.soc` 不为空，路径中还需要包含该关键字。

tag 候选条件：

- 文件名包含 `tag`。
- 文件名包含 `logic.target_date`。

tag 文本解析规则：

- 从 `msg: "..."` 中提取 tag 文本。
- 支持末尾时间格式 `YYYY/MM/DD HH:MM:SS`。
- 支持末尾时间格式 `M/D/YYYY, HH:MM:SS AM/PM`。
- 时间前的文本作为 tag 名称。

record 匹配规则：

- 从 record 文件名最后一段 `HHMMSS` 提取 record 起始时间。
- 查询窗口是 `[tag_time - before, tag_time + after)`。
- 窗口内 record 会被选中。
- 每个 SOC 会额外补一个窗口开始前最近的 record，避免切片起点缺前置数据。

查询结果会生成 `TaskEntry`，按 tag 时间排序并分配两位数 ID。

## 11. 数据结构和字段

### 11.1 查询结果 `TaskEntry`

`TaskEntry` 是查询结果在程序内的结构。

| 字段 | 含义 |
| --- | --- |
| `id` | 查询结果序号，格式如 `01`。 |
| `time` | tag 时间，格式 `YYYY-MM-DD HH:MM:SS`。 |
| `name` | tag 名称。 |
| `paths` | 匹配到的全部 record 路径。 |
| `soc_paths` | 按 SOC 分组的路径，例如 `soc1`、`soc2`。 |

### 11.2 `meta.json`

切片成功后，tag 目录下会写入 `meta.json`。

示例：

```json
{
    "tag_info": {
        "name": "tag 名称",
        "time": "2026-05-13 10:15:30",
        "offset_bf": 15,
        "offset_af": 0,
        "abs_start": "2026-05-13T10:15:15",
        "abs_end": "2026-05-13T10:15:30"
    },
    "vehicle": "XZB600007",
    "date": "20260513",
    "last_update": {
        "soc1": "2026-05-13 10:20:00"
    },
    "files": {
        "soc1": [
            "20260513101450.record.00001.101450.split"
        ]
    }
}
```

字段说明：

| 字段 | 含义 |
| --- | --- |
| `tag_info.name` | tag 名称。 |
| `tag_info.time` | tag 原始时间。 |
| `tag_info.offset_bf` | tag 前窗口秒数，即 `before`。 |
| `tag_info.offset_af` | tag 后窗口秒数，即 `after`。 |
| `tag_info.abs_start` | 切片和回播窗口绝对开始时间。 |
| `tag_info.abs_end` | 切片和回播窗口绝对结束时间。 |
| `vehicle` | 车辆号。 |
| `date` | 数据日期。 |
| `last_update` | 每个 SOC 最近一次成功写入元数据的时间。 |
| `files` | 每个 SOC 下可回播的 `.split` 文件名列表。 |

自动扫描回播只认 `meta.json` 中登记且实际存在的文件。

### 11.3 回播记录 `ReplayRecord`

`ReplayRecord` 是回播命令构造时使用的单条记录。

| 字段 | 含义 |
| --- | --- |
| `path` | record 或 `.split` 文件路径。 |
| `begin` | 该组回播的起始绝对时间。 |
| `duration` | 可播放总时长，单位秒。 |

### 11.4 本地回播库缓存 `local_library.json`

路径：

```text
<work_dir>/.witt/local_library.json
```

结构：

```json
{
    "fingerprint": "13_1715570000.0",
    "library": [
        {
            "tag": "tag 名称",
            "time": "2026-05-13 10:15:30",
            "last_update": {
                "soc1": "2026-05-13 10:20:00"
            },
            "socs": {
                "soc1": [
                    {
                        "path": "/media/road_test/20260513/XZB600007/01.20260513_101530/soc1/a.record.split",
                        "begin": "2026-05-13T10:15:15",
                        "duration": 15
                    }
                ]
            }
        }
    ]
}
```

字段说明：

| 字段 | 含义 |
| --- | --- |
| `fingerprint` | 工作目录修改时间指纹，用于判断缓存是否可复用。 |
| `library[].tag` | tag 名称。 |
| `library[].time` | tag 时间。 |
| `library[].last_update` | 从 `meta.json` 继承的 SOC 更新时间。 |
| `library[].socs` | 按 SOC 分组的回播记录列表。 |

### 11.5 回播历史 `replay_history.json`

路径：

```text
~/.witt/replay_history.json
```

结构：

```json
{
    "entries": [
        {
            "created_at": "2026-05-13 10:25:00",
            "source_type": "auto",
            "replay_mode": "standard",
            "display_tag": "tag 名称",
            "issue_timestamp": "2026-05-13 10:15:30",
            "vehicle": "XZB600007",
            "target_date": "20260513",
            "records": [],
            "start_sec": 0,
            "end_sec": 0,
            "playback_rate": 1.0,
            "channel_filters": []
        }
    ]
}
```

字段说明：

| 字段 | 含义 |
| --- | --- |
| `created_at` | 历史记录创建时间。 |
| `source_type` | 回播来源：`auto`、`full_source`、`manual`、`history`。 |
| `replay_mode` | 回播模式：`standard` 或 `traffic_light`。 |
| `display_tag` | 展示用 tag 或文件名摘要。 |
| `issue_timestamp` | 用于 issue 草稿命名和展示的 tag 时间。 |
| `vehicle` | 车辆号。 |
| `target_date` | 数据日期。 |
| `records` | 本次回播的 `ReplayRecord` 列表。 |
| `start_sec` | 回播起点秒数。 |
| `end_sec` | 回播终点秒数，`0` 表示播放到结尾。 |
| `playback_rate` | 播放倍速。 |
| `channel_filters` | 本次回播使用的 `-k` channel 列表。 |

历史最多保留 50 条。

### 11.6 Issue 草稿

回播结束后，如果进入问题标记流程，Witt 会在以下目录生成 issue 草稿：

```text
<work_dir>/issues/issue_<timestamp>.md
```

草稿包含：

- 建议标题。
- tag 名称。
- 车辆和 tag 时间。
- 问题和预期描述。
- version 文件原文。
- 回播命令。

如果记录了问题时间点，草稿中的回播命令会把 `-s` 调整到该时间点。

## 12. 常见问题

### 查询不到 record

检查以下项：

- 日期是否与文件名前缀一致。
- 车号是否和目录一致。
- 本地、NAS、车端模式是否选对。
- tag 文件名是否同时包含 `tag` 和日期。
- record 文件名是否以日期开头且包含 `record`。
- `logic.soc` 是否设置过窄，例如只设置了 `soc1`。

### 切片批次被跳过

常见原因：

- record 所在目录没有 `version*` 文件。
- record 文件损坏或容器内无法读取。
- channel 过滤后切片命令失败。
- 车端模式下远端 `.split` 拉取失败。

失败批次会清理当前 tag 目录，避免留下半成品。

### 回播提示路径不能映射

Docker 回播只接受位于 `docker.host_mount` 下的宿主机路径。默认要求 record 或 `.split` 位于 `/media` 下。需要把数据移动到挂载目录，或调整 `docker.host_mount` 和 `docker.docker_mount`。

### 自动扫描为空

检查以下项：

- 当前 `host.dest_root`、`logic.target_date`、`logic.vehicle` 组合是否指向正确工作目录。
- 目标目录下是否存在 `meta.json`。
- `meta.json` 中登记的 `.split` 文件是否还存在。
- 切片是否成功写入对应 SOC 目录。

### 环境恢复失败

检查以下项：

- version 文件是否存在。
- version 文件是否包含 `mdrive` 和 `mdrive_conf`。
- `host.mdrive_root/vmc.sh` 是否存在且包含所需变量。
- Docker 容器、Supervisor、显示环境是否正常。

### 历史回播失败

历史记录只保存当时的路径和参数，不复制数据。如果原始文件或 `.split` 文件被移动或删除，需要重新选择数据回播，或执行 `history clear` 清理无效历史。
