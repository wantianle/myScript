# Witt 架构说明

## 文档目的

本文档描述当前 `witt` 的完成态架构：入口、分层边界、核心链路、数据契约、执行通道、异常流和测试护栏。

面向使用者的功能说明、字段解释和排障步骤见 [USER_MANUAL.md](/home/mini/dev/myScript/witt/USER_MANUAL.md)。本文只讨论代码结构和维护约束。

## 当前状态

当前项目已经完成核心链路重构：

- 终端入口已统一为命令驱动 REPL。
- 查询、切片、回播、环境恢复、回播栈启动、回播历史和 issue 草稿生成都由 Python 模块承载。
- `core/` 不直接输出 UI 文案，展示和用户输入由 `interface/` 负责。
- `meta.json`、本地回播库缓存、回播历史和配置对象都已有 dataclass/TypedDict 边界。
- Shell 脚本只保留为安装、部署、SSH 辅助、补丁和 vmc 包装等环境工具。

## 运行约束

- Python 基线版本：`3.8`
- 新代码必须兼容 Python 3.8。
- 不使用 Python 3.9+/3.10+ 语法：
  - 不使用 `list[str]`
  - 不使用 `dict[str, int]`
  - 不使用 `X | Y`
- 类型标注优先使用：
  - `typing.List`
  - `typing.Dict`
  - `typing.Tuple`
  - `typing.Optional`
  - `typing.Union`
- 测试框架使用标准库 `unittest`。

## 入口和会话装配

### 顶层入口

[main.py](/home/mini/dev/myScript/witt/main.py) 是本地入口，只负责调用 [interface/cli.py](/home/mini/dev/myScript/witt/interface/cli.py) 的 `menu()`。

实际启动链路：

```text
main.py
  -> interface.cli.menu()
  -> AppSession()
  -> TaskContext(config)
  -> RuntimeCoordinator + repositories + engines
  -> REPL command loop
```

### 配置初始化

[core/session.py](/home/mini/dev/myScript/witt/core/session.py) 中的 `ensure_user_config_path()` 负责保证用户配置存在：

```text
config/settings.yaml -> ~/.witt/settings.yaml
```

后续会话默认读取 `~/.witt/settings.yaml`。`config` 命令会打开该文件，编辑器退出后重新构造 `AppSession`。

### `AppSession`

`AppSession` 是应用装配根，集中创建和持有：

- `ctx`: [core/context.py](/home/mini/dev/myScript/witt/core/context.py) 的 `TaskContext`
- `runtime`: [core/runner.py](/home/mini/dev/myScript/witt/core/runner.py) 的 `RuntimeCoordinator`
- `recorder`: [core/engine/recorder.py](/home/mini/dev/myScript/witt/core/engine/recorder.py) 的 `Recorder`
- `metadata_repository`: `MetadataRepository`
- `library_cache_repository`: `LibraryCacheRepository`
- `replay_history_repository`: `ReplayHistoryRepository`
- `record_downloader`: `RecordDownloader`
- `player`: `RecordPlayer`

执行器通过属性按需创建：

- `source_executor`
  - `logic.mode != 3` 时使用 `DockerAdapter`
  - `logic.mode == 3` 时使用 `SSHAdapter`
- `playback_executor`
  - 回播始终使用 `DockerAdapter`

## 分层设计

### `interface/`

`interface/` 负责终端输入、展示和用例级编排。它可以调用 `core/` 服务，但不应实现底层业务规则。

- [interface/cli.py](/home/mini/dev/myScript/witt/interface/cli.py)
  - REPL 主循环
  - 命令别名解析后的分发
  - 顶层异常兜底
  - `config`、`clear`、`history` 子命令处理

- [interface/ui.py](/home/mini/dev/myScript/witt/interface/ui.py)
  - Rich 展示层
  - banner、帮助、环境摘要、列表、结果、进度、回播信息、历史表格
  - 不做 prompt，不做业务判断

- [interface/prompter.py](/home/mini/dev/myScript/witt/interface/prompter.py)
  - PromptToolkit 基础输入层
  - 命令解析、文本输入、确认输入、选项选择、序号表达式、关键字筛选
  - 维护命令规格 `COMMAND_SPECS`

- [interface/prompter_config.py](/home/mini/dev/myScript/witt/interface/prompter_config.py)
  - 日期、车号、数据源、导出路径、切片/回播窗口、version 文件输入
  - 车辆号格式校验

- [interface/prompter_replay.py](/home/mini/dev/myScript/witt/interface/prompter_replay.py)
  - 回播条目选择
  - SOC 选择
  - 历史条目选择
  - 播放范围、倍速、问题标记、手动路径输入

- [interface/prompter_channel.py](/home/mini/dev/myScript/witt/interface/prompter_channel.py)
  - 从 record 中读取 channel 并聚合候选项
  - 交互选择需要删除的 channel

- [interface/workflow.py](/home/mini/dev/myScript/witt/interface/workflow.py)
  - 主用例编排
  - `slice`、`replay`、`scan`、`manual`、`history` 的入口函数
  - 负责连接 prompt、core 服务和回播编排

- [interface/workflow_replay.py](/home/mini/dev/myScript/witt/interface/workflow_replay.py)
  - 回播编排层
  - 标准回播、原始数据回播、手动回播、历史回播、红绿灯回灌
  - 环境恢复入口
  - 回播历史保存
  - issue 草稿生成入口

### `core/`

`core/` 负责应用模型、业务服务、执行适配、仓储和运行协调。`core/` 不直接调用 `interface.ui`。

- [core/models.py](/home/mini/dev/myScript/witt/core/models.py)
  - dataclass 领域模型
  - TypedDict 原始边界 schema
  - 配置对象、查询结果、回播记录、历史记录、回播库、metadata、record info

- [core/context.py](/home/mini/dev/myScript/witt/core/context.py)
  - 加载 YAML 配置并转换为 `AppConfig`
  - 暴露 `ctx.host`、`ctx.remote`、`ctx.docker`、`ctx.paths`、`ctx.logic`
  - 计算 `work_dir`、`log_dir`
  - 初始化日志器
  - 生成本地回播库指纹

- [core/session.py](/home/mini/dev/myScript/witt/core/session.py)
  - 应用装配根
  - 用户配置初始化
  - 执行器选择

- [core/runner.py](/home/mini/dev/myScript/witt/core/runner.py)
  - 运行时协调服务
  - 查询入口 `run_find_record()`
  - 环境恢复 `restore_runtime_environment()`
  - 回播栈启动 `start_standard_replay_stack()` / `start_traffic_light_stack()`
  - 结构化包装底层错误为 `ScriptExecutionError`

- [core/repository.py](/home/mini/dev/myScript/witt/core/repository.py)
  - `LibraryCacheRepository`: 读写 `<work_dir>/.witt/local_library.json`
  - `MetadataRepository`: 读写和扫描 `meta.json`
  - `ReplayHistoryRepository`: 读写 `~/.witt/replay_history.json`

- [core/errors.py](/home/mini/dev/myScript/witt/core/errors.py)
  - 核心层异常定义
  - 区分路径映射、命令执行、查询、record info、切片、环境恢复和回播栈错误

- [core/issue_draft.py](/home/mini/dev/myScript/witt/core/issue_draft.py)
  - issue 草稿数据模型
  - issue Markdown 渲染和落盘
  - 从 `vmc.sh` 生成建议标题
  - 将数据路径尽力映射为 NAS 展示路径

### `core/adapter/`

执行通道适配层只处理命令执行、路径映射和文件拉取，不承载业务规则。

- [core/adapter/docker.py](/home/mini/dev/myScript/witt/core/adapter/docker.py)
  - `docker exec` 命令构造
  - source `docker.setup_env`
  - 宿主机路径到容器路径映射
  - 本地复制和删除

- [core/adapter/ssh.py](/home/mini/dev/myScript/witt/core/adapter/ssh.py)
  - SSH/SCP 选项统一
  - source 远端环境
  - 远端命令执行、远端文件删除、远端文件拉取
  - 车端路径保持原样映射

### `core/engine/`

业务服务层承载核心规则。

- [core/engine/record_query.py](/home/mini/dev/myScript/witt/core/engine/record_query.py)
  - 按 `logic.mode` 分发本地、NAS、车端查询
  - 本地模式查询 `host.data_root`
  - NAS 模式查询 `host.nas_root/<date>/<vehicle>`
  - 车端模式通过 SSH 获取候选路径和 tag 文本

- [core/engine/record_finder.py](/home/mini/dev/myScript/witt/core/engine/record_finder.py)
  - tag 文本解析
  - record 文件索引
  - 时间窗匹配
  - `TaskEntry` 构造和稳定 ID 分配

- [core/engine/downloader.py](/home/mini/dev/myScript/witt/core/engine/downloader.py)
  - 切片批次规划
  - version 文件校验和同步
  - `cyber_recorder split`
  - 远端临时 `.split` 清理和拉取
  - 失败批次清理
  - `meta.json` 写入

- [core/engine/recorder.py](/home/mini/dev/myScript/witt/core/engine/recorder.py)
  - `cyber_recorder info`
  - `cyber_recorder split`
  - 输出解析委托给 `utils.parser`

- [core/engine/player.py](/home/mini/dev/myScript/witt/core/engine/player.py)
  - 扫描 `meta.json` 构造本地回播库
  - 读写回播库缓存
  - 生成 `cyber_recorder play` 命令
  - 处理回播范围、倍速、channel 过滤和路径映射

- [core/engine/runtime_env.py](/home/mini/dev/myScript/witt/core/engine/runtime_env.py)
  - 解析 JSON/TXT version 文件
  - 更新 `vmc.sh` 中的 MDrive 版本、配置版本、模型、地图、车号和车型
  - 仅在运行环境发生变化时触发 `vmc.sh`

- [core/engine/replay_stack.py](/home/mini/dev/myScript/witt/core/engine/replay_stack.py)
  - 标准回播栈启动
  - 红绿灯回灌栈启动
  - 同步 multiviz/camera 配置到容器
  - 启动 Dreamview、Debug Driver、Perception 相关节点

### `utils/`

[utils/parser.py](/home/mini/dev/myScript/witt/utils/parser.py) 是纯解析工具层：

- `cyber_recorder info` 输出解析
- 文件名清洗
- Cyber 时间字符串转换
- 回播范围解析
- record 文件排序

该层不依赖 `interface/` 和 `core` 服务对象，不做终端交互。

### `scripts/`

`scripts/` 保留环境和部署辅助脚本：

- [scripts/setup.sh](/home/mini/dev/myScript/witt/scripts/setup.sh)
- [scripts/vmc.sh](/home/mini/dev/myScript/witt/scripts/vmc.sh)
- [scripts/vmc_deploy.sh](/home/mini/dev/myScript/witt/scripts/vmc_deploy.sh)
- [scripts/ssh.sh](/home/mini/dev/myScript/witt/scripts/ssh.sh)
- [scripts/patch.sh](/home/mini/dev/myScript/witt/scripts/patch.sh)
- [scripts/utils.sh](/home/mini/dev/myScript/witt/scripts/utils.sh)

业务判断、查询、切片、回播、环境恢复和回播栈启动不应再迁回 shell。

## 命令和用例链路

### REPL 分发

[interface/cli.py](/home/mini/dev/myScript/witt/interface/cli.py) 将命令映射到 workflow：

| 命令 | 编排函数 |
| --- | --- |
| `slice` | `workflow.slice_progress()` |
| `replay` | `workflow.full_source_progress()` |
| `scan` | `workflow.auto_replay_progress()` |
| `manual` | `workflow.manual_replay_progress()` |
| `history` | `workflow.replay_history_progress()` 或 history 子命令 |
| `traffic` | `workflow_replay.traffic_light_replay_flow()` |
| `env` | `ui.show_environment_summary()` |
| `config` | 重新编辑配置并重建 `AppSession` |

### 查询链路

```text
workflow.search_flow()
  -> prompter_config 收集日期、车号、数据源、窗口
  -> session.runtime.run_find_record()
  -> RecordQueryService.run_query()
  -> record_finder.find_local_tasks()
     或 record_finder.find_tasks_from_path_texts()
  -> List[TaskEntry]
```

查询规则：

- record 文件名以目标日期开头并包含 `record`。
- tag 文件名包含 `tag` 和目标日期。
- `logic.soc` 不为空时，record 路径必须包含该过滤关键字。
- record 起始时间从文件名末尾 `HHMMSS` 提取。
- 匹配窗口为 `[tag_time - before, tag_time + after)`。
- 每个 SOC 会补一个窗口开始前最近的 record。

### 切片链路

```text
workflow.slice_progress()
  -> 查询 TaskEntry
  -> 选择 tag
  -> 可选 channel 过滤
  -> RecordDownloader.plan_download()
  -> RecordDownloader.download_records()
  -> Recorder.split()
  -> MetadataRepository.save(meta.json)
  -> 可选 workflow_replay.auto_replay_flow()
```

失败处理：

- 批次规划时缺少 `version*` 会进入 skipped。
- 单个 SOC 切片失败会清理整个 tag 目录。
- 同一 tag 中一个 SOC 失败后，该 tag 已完成的 SOC 也不再计为成功。
- 车端模式会清理远端临时 `.split`。

### 自动扫描回播链路

```text
workflow.auto_replay_progress()
  -> 更新扫描根目录
  -> workflow_replay.auto_replay_flow()
  -> RecordPlayer.load_library()
  -> MetadataRepository.iter_record_meta()
  -> LibraryCacheRepository.save/load()
  -> 选择 LibraryEntry
  -> 选择 SOC 或 All
  -> _replay_records()
```

本地回播库由 `meta.json` 恢复，缓存写入 `<work_dir>/.witt/local_library.json`。

### 原始数据回播链路

```text
workflow.full_source_progress()
  -> 查询 TaskEntry
  -> 选择单个 tag
  -> workflow_replay.full_source_replay_flow()
  -> _build_source_replay_records()
  -> _replay_records()
```

该链路不写入 `meta.json`，直接基于原始 record 构造回播记录。

### 手动回播链路

```text
workflow.manual_replay_progress()
  -> prompter_replay.get_manual_replay_paths()
  -> Recorder.get_info(first/last)
  -> 构造 ReplayRecord
  -> _replay_records()
```

手动输入可以是单文件、多文件或目录。目录会递归收集文件名包含 `.record` 的文件，并按 record 序号排序。

### 红绿灯回灌链路

```text
workflow_replay.traffic_light_replay_flow()
  -> 选择自动扫描或手动文件
  -> 准备 ReplayRecord
  -> channel 过滤
  -> restore_environment_flow(..., traffic_light)
  -> 可选标准回播栈
  -> 可选红绿灯回灌栈
  -> cyber_recorder play
```

红绿灯回灌额外启动 Debug_Driver-Camera、Perception-TrafficLight 等节点，并启用相关 debug 图保存配置。

### 回播执行链路

所有回播模式最终进入 [interface/workflow_replay.py](/home/mini/dev/myScript/witt/interface/workflow_replay.py) 的 `_replay_records()`：

```text
ReplayRecord 列表
  -> 输入播放范围和倍速
  -> RecordPlayer.build_playback_plan()
  -> 首轮回播前 restore_environment_flow()
  -> ui.show_playback_info()
  -> ReplayHistoryRepository.save()
  -> playback_executor.execute_interactive()
  -> 可继续调整范围和倍速
  -> issue marker
  -> save_issue_draft()
```

运行环境只在同一轮 `_replay_records()` 中准备一次。用户选择继续调整播放范围时，不会重复恢复环境和启动回播栈。

## 数据模型边界

### 配置模型

配置读取后转换为以下 dataclass：

- `AppConfig`
- `HostConfig`
- `RemoteConfig`
- `DockerConfig`
- `PathsConfig`
- `LogicConfig`

业务代码应使用：

```python
ctx.host.dest_root
ctx.remote.ip
ctx.docker.container
ctx.paths.scripts_dir
ctx.logic.before
```

不要重新传递 YAML 原始 dict。

### 查询和切片模型

- `TaskEntry`
  - 查询结果
  - 字段：`id`、`time`、`name`、`soc_paths`、`paths`
- `DownloadItem`
  - 单个切片输入输出文件
- `DownloadBatch`
  - 某个 tag 的某个 SOC 批次
- `DownloadSummary`
  - 总文件数、成功批次、跳过批次、失败批次
- `SkippedBatch`
  - 规划阶段跳过原因
- `FailedBatch`
  - 执行阶段失败原因

### 回播模型

- `ReplayRecord`
  - 回播文件、起始时间、持续时长
- `LibraryEntry`
  - 从 `meta.json` 恢复的回播库条目
- `LibraryLoadResult`
  - 回播库加载结果和缓存命中状态
- `PlaybackPlan`
  - 最终 `cyber_recorder play` 命令、总时长、展示 tag、倍速
- `ReplayHistoryEntry`
  - 一次回播的可复用历史记录
- `RecordInfo`
  - `cyber_recorder info` 解析结果
- `ChannelInfo`
  - channel 名称和消息数量

### 元数据模型

- `TagInfo`
  - tag 名称、时间、窗口偏移、绝对起止时间
- `RecordMeta`
  - `meta.json` 的领域模型
  - 负责从 `TaskEntry` 构造 metadata、合并已有 metadata、更新 SOC 文件列表、恢复 `ReplayRecord`

`meta.json` 的读写必须通过 `MetadataRepository` 和 `RecordMeta` 完成。

### Issue 模型

- `ReplayIssueMarker`
  - 回播结束后用户标记的问题秒数和描述
- `IssueDraft`
  - issue 草稿渲染所需字段

issue 草稿由 `core.issue_draft.save_issue_draft()` 写入 `<work_dir>/issues`。

## 原始边界 Schema

[core/models.py](/home/mini/dev/myScript/witt/core/models.py) 中的 `TypedDict` 用来描述外部原始结构：

- `RawLogicConfig`
- `RawHostConfig`
- `RawRemoteConfig`
- `RawDockerConfig`
- `RawPathsConfig`
- `RawAppConfig`
- `RawReplayRecord`
- `RawReplayHistoryEntry`
- `RawLibraryEntry`
- `RawRecordMeta`

使用原则：

- 文件、缓存、YAML、JSON 边界使用 TypedDict 描述。
- 应用内部使用 dataclass。
- 数据转换集中在模型类的 `from_dict`、`from_cache_dict`、`to_dict`、`to_cache_dict` 等方法。
- 不让 `Dict[str, Any]` 在业务层到处流转。

## 持久化文件

| 文件 | 负责模块 | 用途 |
| --- | --- | --- |
| `~/.witt/settings.yaml` | `core.session` / `core.context` | 用户配置。 |
| `<work_dir>/<tag_dir>/meta.json` | `MetadataRepository` | 切片结果元数据，自动扫描回播的事实来源。 |
| `<work_dir>/.witt/local_library.json` | `LibraryCacheRepository` | 本地回播库缓存。 |
| `~/.witt/replay_history.json` | `ReplayHistoryRepository` | 最近回播历史，默认最多 50 条。 |
| `<work_dir>/.witt/log/*.log` | `TaskContext.setup_logger()` | 当前车号和日期下的运行日志。 |
| `<work_dir>/issues/issue_*.md` | `core.issue_draft` | 回播后生成的 issue 草稿。 |

## 执行通道

### 本地和 NAS

本地和 NAS 模式都使用 `DockerAdapter` 执行 `cyber_recorder`：

```text
host path
  -> DockerAdapter.map_path()
  -> docker mount path
  -> docker exec <container> bash -lc "source setup_env && command"
```

路径必须位于 `docker.host_mount` 下，默认是 `/media`。

### 车端

车端模式使用 `SSHAdapter`：

```text
ssh remote
  -> source setup_env
  -> cyber_recorder split/info
  -> scp 拉回 .split
```

远端路径不做 Docker 映射。切片时会先在远端生成临时 `.split`，拉回后清理远端临时文件。

### 回播

回播始终在本地 Docker 容器中执行。即使数据来自车端，最终回播文件也必须落到本地并能映射到容器路径。

## 异常处理规则

异常分层：

- `adapter` 将命令失败包装为 `CommandExecutionError` 或 `PathMappingError`。
- `engine` 抛出领域异常，例如 `FindRecordError`、`RecordInfoError`、`RecordSplitError`、`RuntimeEnvironmentError`、`ReplayStackError`。
- `runner` 将运行时入口失败包装为 `ScriptExecutionError`，提供 `operation_name`、`summary`、`details`。
- `interface` 捕获异常，决定展示为 `WARN` 或 `ERROR`，并给出下一步提示。

核心规则：

- `core/` 不直接调用 `ui`。
- `interface/` 不解析底层命令输出。
- 捕获异常后如果需要保留原因，使用 `raise SomeError(...) from e`。
- 避免无意义的 `except Exception as e: raise e`。

## 日志边界

`TaskContext.setup_logger()` 负责初始化全局日志：

```text
<work_dir>/.witt/log/witt_<timestamp>.log
```

日志用于保留调试信息；用户可见的信息仍由 `interface/ui.py` 统一展示。

## 测试护栏

当前测试覆盖已经覆盖主要分层：

- `tests/test_cli.py`
- `tests/test_workflow.py`
- `tests/test_replay_workflow.py`
- `tests/test_flow_integration.py`
- `tests/test_config_context.py`
- `tests/test_config_prompter.py`
- `tests/test_replay_prompter.py`
- `tests/test_channel_prompter.py`
- `tests/test_models_parser.py`
- `tests/test_repository.py`
- `tests/test_record_finder.py`
- `tests/test_record_query.py`
- `tests/test_downloader.py`
- `tests/test_player.py`
- `tests/test_runtime_env.py`
- `tests/test_replay_stack.py`
- `tests/test_issue_draft.py`
- `tests/test_adapter.py`
- `tests/test_runner.py`
- `tests/test_session.py`
- `tests/test_tui_helpers.py`

推荐本地验证命令：

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

没有虚拟环境时：

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

语法扫查：

```bash
python3 -m py_compile $(find . -path '*/.venv' -prune -o -name '*.py' -print)
```

## 维护规则

### 新功能归属

- 终端展示：放在 `interface/ui.py`。
- 用户输入：放在对应 `prompter_*.py`。
- 用例编排：放在 `interface/workflow.py` 或 `interface/workflow_replay.py`。
- 业务规则：放在 `core/engine/`。
- 持久化：放在 `core/repository.py`。
- 数据结构：放在 `core/models.py`。
- 命令执行：放在 `core/adapter/`。
- 运行时入口协调：放在 `core/runner.py`。

### 数据契约

- 新增文件或缓存格式时，先定义 TypedDict 原始边界，再定义 dataclass 内部模型。
- `meta.json`、回播库缓存、回播历史不要在 workflow 中手拼 dict。
- 字段转换集中在模型和 repository。

### Shell 边界

- 安装、部署、SSH 辅助、补丁脚本可以继续留在 `scripts/`。
- 查询、切片、回播、环境恢复、回播栈启动、metadata 和历史记录不要迁回 shell。

### 变更自检

改动前确认：

1. 这段逻辑属于哪一层？
2. 是否能复用现有 dataclass 或 repository？
3. 是否把 UI 展示留在 `interface/`？
4. 是否把命令执行限制在 adapter 或 runner？
5. 是否需要补一个 focused `unittest`？

