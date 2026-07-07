# DESIGN

## 1. Overview

该工具是一个运行在 Orin 域控台架上的 Python 3.8 命令行冒烟测试执行器，用于自动化每日开环基线数据生成流程：

1. 读取人工维护的数据集清单。
2. 使用 `md-tool` 在 soc1 安装目标软件版本并启动 `mdrive` 服务。
3. 将原始传感器数据从 `/media/nas` 同步到 `/mdrive_data` 本地工作目录。
4. 切换 `soc1` 和 `soc2` 的底软模块状态。
5. 在 `soc2` 直接启动 `mkit record` 进行录制。
6. 使用 `mkit play` 单次回灌原始数据。
7. 停止并收尾录制。
8. 采集版本、命令、输出文件和 `mkit info` 元数据。
9. 产出机器可读和人工可读的运行总结。

MVP 明确采用本地脚本/工具架构，而不是服务化架构。它运行在离线 Ubuntu 20.04 台架环境中，只依赖现有 bench 工具。设计重点是：显式流程步骤、fail-fast 行为、完整日志与明确可追溯性，而不是重型抽象；同时模块边界和结果产物应保持清晰，便于后续在需要时向服务化架构演进。

工具支持两种模式：

- **一键模式**：对一个或多个数据集执行完整流程。
- **Debug 分步模式**：基于同一套执行引擎和接口契约，单独执行某个步骤。

MVP 明确不包含：HTML 报告、NAS 自动回传、算法自动验证、Web UI、分布式调度、复杂插件系统。

---

## 2. Module Tree

```text
bench_smoke/
├── cli.py
│   └── depends on orchestrator, config, manifest, logging_setup
│
├── config.py
│   └── depends on models
│
├── models.py
│
├── manifest.py
│   └── depends on models
│
├── orchestrator.py
│   └── depends on models, versioning, data_prep, module_control,
│                 playback, recorder, metadata, result_store, step_runner
│
├── step_runner.py
│   └── depends on command_runner, result_store, models
│
├── command_runner.py
│   └── depends on models
│
├── versioning.py
│   └── depends on command_runner, models
│
├── data_prep.py
│   └── depends on command_runner, models
│
├── module_control.py
│   └── depends on command_runner, models
│
├── recorder.py
│   └── depends on command_runner, models
│
├── playback.py
│   └── depends on command_runner, models
│
├── metadata.py
│   └── depends on command_runner, models
│
├── result_store.py
│   └── depends on models
│
├── logging_setup.py
│
└── extensions/
    ├── report_stub.py
    ├── upload_stub.py
    └── validation_stub.py
```

运行时依赖方向必须保持单向：

```text
cli
  -> orchestrator
      -> step modules
          -> command_runner
      -> result_store
  -> manifest/config/logging
```

各 step module 之间不得直接互调；跨步骤编排只允许出现在 `orchestrator.py`。

---

## 3. Module Responsibilities

### `cli.py`

解析命令行参数，并分发到完整一键执行或单步 debug 执行。它不应包含业务流程逻辑，只负责入口层命令和模式选择。

### `config.py`

加载静态配置，例如 soc 连接信息、模块名、默认路径、回灌 topic 集合、超时值和输出目录命名规则，并向系统提供校验后的配置对象。

### `models.py`

定义共享 dataclass / enum，例如数据集对象、运行上下文、步骤结果、命令结果、版本信息、录制产物和最终汇总对象。该模块不得包含 shell 执行和文件系统副作用。

### `manifest.py`

读取并校验人工维护的数据集清单，将原始配置行转换为 `DatasetEntry`。缺字段、重复 ID、路径异常等问题要尽早失败。

### `orchestrator.py`

负责高层工作流顺序、fail-fast 策略和清理策略。它是唯一允许决定“下一个跑什么步骤”的模块。

### `step_runner.py`

提供统一的步骤执行包装：开始/结束日志、异常捕获、耗时统计、步骤结果落盘、失败归一化为 `StepResult`。

### `command_runner.py`

执行本地命令和 SSH 远程命令，统一处理 timeout、stdout/stderr 捕获、返回码校验和结构化日志。只有该模块可以直接调用 subprocess。

### `versioning.py`

负责通过 `md-tool` 在 soc1 执行版本安装与服务启动，记录安装命令、执行结果以及必要的版本信息摘要。

### `data_prep.py`

通过 `rsync` 将原始数据从数据集清单给出的源路径复制到 `/mdrive_data/base_test` 本地工作目录，并记录路径与拷贝结果。

### `module_control.py`

通过 SSH 和 `supervisorctl` 控制 `soc1` / `soc2` 的底软模块，关闭回灌前必须停掉的生产模块，启动回灌依赖的 debug 模块。

### `recorder.py`

负责在 `soc2` 直接启动、监控并停止/收尾 `mkit record` 录制进程，并在回灌后发现生成的 `.mcap` 文件。

### `playback.py`

基于本地化后的数据路径和固定 topic 集，运行一次 `mkit play` 单次回灌。MVP 中绝不允许启用 loop 模式。

### `metadata.py`

采集回灌后元数据：版本信息摘要、生成的 `.mcap` 的 `mkit info`、输出文件路径及基础文件信息。

### `result_store.py`

创建每次运行的输出目录，并写入 JSON/text 记录：step 结果、命令日志、数据集汇总和最终运行总结，为后续 HTML/NAS/算法验证留下稳定接口。

### `logging_setup.py`

配置终端和文件日志，确保每次运行都有固定日志根目录和统一格式。

### `extensions/report_stub.py`

预留未来 HTML 报告扩展点，但 MVP 不实现 HTML。

### `extensions/upload_stub.py`

预留未来 NAS 自动上传扩展点，但 MVP 不执行上传。

### `extensions/validation_stub.py`

预留未来算法验证扩展点，但 MVP 不执行验证。

---

## 4. Interface Contracts

### Shared Data Types

#### `DatasetEntry`

```python
@dataclass
class DatasetEntry:
    dataset_id: str
    issue_description: str
    feishu_url: str
    source_path: str
    tags: List[str] = field(default_factory=list)
```

Contract:

- `dataset_id`、`issue_description`、`feishu_url`、`source_path` 必填。
- `source_path` 必须是绝对路径，且能在 bench 主机上解析。
- 校验失败必须在任何安装/拷贝/模块切换动作之前终止。

#### `PackageSpec`

```python
@dataclass
class PackageSpec:
    package: str
    version: str
    install_with_deps: bool = True
```
```

Contract:

- 第一版至少支持 2~3 个安装包配置。
- `mdrive_map` 可作为可选安装项，也可表达为一个 `PackageSpec`。
- 所有版本号必须由用户显式传入，不做自动推断。

#### `ToolConfig`

```python
@dataclass
class ToolConfig:
    nas_root: str
    local_data_root: str
    run_root: str
    local_copy_root: str
    record_root: str
    soc1_host: str
    soc1_user: str
    soc1_port: int
    soc2_host: str
    soc2_user: str
    soc2_port: int
    ssh_password: Optional[str]
    stop_modules_soc1: List[str]
    stop_modules_soc2: List[str]
    start_debug_modules_soc2: List[str]
    playback_topics: List[str]
    package_specs: List[PackageSpec]
    record_command_template: str
    mount_check_path: str
    command_timeout_sec: int
    install_timeout_sec: int
    rsync_timeout_sec: int
    playback_timeout_sec: int
    recorder_start_timeout_sec: int
    recorder_stop_timeout_sec: int
```

默认值应覆盖当前 bench 事实：

- `nas_root=/media/nas`
- `local_data_root=/mdrive_data`
- `local_copy_root=/mdrive_data/base_test`
- `soc1_host=192.168.10.2`, `soc1_user=nvidia`, `soc1_port=22`
- `soc2_host=192.168.10.3`, `soc2_user=nvidia`, `soc2_port=22`
- `mount_check_path=/media/nas`

Contract:

- 所有路径必须为绝对路径。
- `playback_topics` 必须非空。
- `record_command_template` 必须允许注入输出路径。
- soc 连接信息、模块列表、包列表缺失都属于配置错误。
- 密码获取方式允许 Phase 3 再决定，但不得散落在多个模块中；统一由 `command_runner` 或配置入口处理。

#### `RunContext`

```python
@dataclass
class RunContext:
    run_id: str
    run_dir: str
    dataset: DatasetEntry
    packages: List[PackageSpec]
    local_dataset_path: Optional[str] = None
    record_output_dir: Optional[str] = None
    generated_mcaps: List[str] = field(default_factory=list)
```

Contract:

- 在任何步骤开始前由 `orchestrator.py` 创建。
- 只允许保存由步骤执行过程中“发现”的可变结果，如 `local_dataset_path`、`generated_mcaps`。
- 每步完成后都要持久化，供 debug 模式复用或排查。

#### `CommandResult`

```python
@dataclass
class CommandResult:
    command: List[str]
    display_command: str
    return_code: int
    stdout: str
    stderr: str
    started_at: str
    ended_at: str
    duration_sec: float
    timed_out: bool = False
```

Contract:

- `stdout` / `stderr` 在失败时也应尽量保留。
- 非 0 返回码默认即失败，除非调用方显式放宽。

#### `StepStatus`

```python
class StepStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
```

#### `StepResult`

```python
@dataclass
class StepResult:
    name: str
    status: StepStatus
    started_at: str
    ended_at: str
    duration_sec: float
    message: str
    commands: List[CommandResult] = field(default_factory=list)
    artifacts: Dict[str, Any] = field(default_factory=dict)
    error_type: Optional[str] = None
    log_path: Optional[str] = None
```

Contract:

- 每个 workflow step 必须返回一个 `StepResult`。
- 失败结果必须带 `message`、`error_type` 和 `log_path`。
- 一键模式遇到第一个 `FAILED` 就停止后续关键步骤。

#### `RunSummary`

```python
@dataclass
class RunSummary:
    run_id: str
    dataset_id: str
    status: StepStatus
    failed_step: Optional[str]
    packages: List[PackageSpec]
    source_path: str
    local_dataset_path: Optional[str]
    record_output_dir: Optional[str]
    generated_mcaps: List[str]
    step_results: List[StepResult]
    summary_path: str
```

Contract:

- 成功或失败都必须写出最终 `RunSummary`。
- 必须能回答：哪个数据、哪些版本、哪些命令、输出在哪、为什么失败。

---

### `cli.py`

#### `main(argv: Optional[List[str]] = None) -> int`

Expected commands:

```text
bench-smoke run \
  --manifest /path/to/datasets.yaml \
  --dataset-id ID1 --dataset-id ID2 \
  --package NAME=VERSION \
  --package NAME=VERSION \
  [--package mdrive_map=VERSION] \
  [--config /path/to/config.yaml]

bench-smoke debug STEP \
  --manifest /path/to/datasets.yaml \
  --dataset-id ID \
  --package NAME=VERSION \
  [--run-id EXISTING_RUN_ID] \
  [--config /path/to/config.yaml]
```

Valid debug `STEP` values:

```text
validate_manifest
inspect_version
install_version
prepare_data
switch_modules
start_recorder
playback
stop_recorder
collect_metadata
summarize
```

Output:

- `0`: 成功
- `1`: workflow / step 失败
- `2`: CLI / 配置 / manifest 校验失败

Failure behavior:

- 非法参数打印清晰用法并返回 `2`。
- 运行期失败返回 `1`，并尽可能写出日志和 summary。

---

### `config.py`

#### `load_config(path: Optional[str]) -> ToolConfig`

Input:

- 可选 YAML / JSON 配置文件路径。
- 不提供时使用内建默认值。

Failure behavior:

- 文件缺失、格式错误或关键项非法时抛出 `ConfigError`。

---

### `manifest.py`

#### `load_manifest(path: str) -> List[DatasetEntry]`

推荐 MVP 格式：YAML。

Example YAML:

```yaml
datasets:
  - dataset_id: "FS-12345"
    issue_description: "Safety takeover case"
    feishu_url: "https://..."
    source_path: "/media/nas/project/raw/case_001"
    tags: ["safety_takeover"]
```

Failure behavior:

- 读不到文件、格式错误、字段缺失、`dataset_id` 重复时抛出 `ManifestError`。

#### `select_datasets(entries: List[DatasetEntry], dataset_ids: List[str]) -> List[DatasetEntry]`

Failure behavior:

- 任一请求 ID 不存在时抛出 `ManifestError`。

---

### `command_runner.py`

#### `run_local(command: List[str], timeout_sec: int, check: bool = True, cwd: Optional[str] = None) -> CommandResult`

Contract:

- 使用 argv 列表而不是 shell 字符串。
- timeout 时强制终止进程。
- `check=True` 时非 0 返回码抛出 `CommandExecutionError`。

#### `run_remote(host: str, port: int, user: str, remote_command: str, timeout_sec: int, check: bool = True) -> CommandResult`

默认命令形态：

```text
ssh -p <port> <user>@<host> <remote_command>
```

Failure behavior:

- SSH 失败、超时、远程命令非 0 时与本地命令一致处理。

Implementation note:

- MVP 保持简单 SSH 调用。
- 如 Phase 3 需要密码输入，可集中到该模块统一处理，不允许业务模块自行拼接交互式逻辑。

---

### `step_runner.py`

#### `run_step(name: str, context: RunContext, fn: Callable[[RunContext], StepResult]) -> StepResult`

Contract:

- 统一记录开始/结束。
- 统一落盘 step result。
- 已知异常转成 `FAILED`。
- 未知异常记录 traceback，并归一为 `UnexpectedError`。

---

### `versioning.py`

#### `inspect_versions(config: ToolConfig) -> VersionSnapshot`

```python
@dataclass
class VersionSnapshot:
    version_info_raw: str
    captured_at: str
```

#### `install_versions(context: RunContext, config: ToolConfig) -> StepResult`

Commands:

```text
ssh nvidia@192.168.10.2 "md install <version>"
ssh nvidia@192.168.10.2 "md install <version>"
...
ssh nvidia@192.168.10.2 "md start"
```

Contract:

- 用户输入的是一组版本组合。
- `mdrive` 和 `mdrive_conf` 为每日更新的核心版本组合成员。
- 地图包可选，不保证每次都安装。

Artifacts:

```python
{
    "before_version_info": "...",
    "after_version_info": "...",
    "installed_packages": [{"package": "...", "version": "..."}]
}
```

Failure behavior:

- 任一安装命令失败即该 step 失败。
- 若已捕获到版本信息摘要，则失败时也应尽量保留。

---

### `data_prep.py`

#### `prepare_dataset(context: RunContext, config: ToolConfig) -> StepResult`

Destination rule:

```text
/mdrive_data/base_test/<dataset_id>/<run_id>/
```

Command:

```text
test -d /media/nas
rsync -a --info=progress2 <source_path>/ <destination_path>/
```

Artifacts:

```python
{
    "source_path": "...",
    "local_dataset_path": "...",
    "rsync_return_code": 0
}
```

Failure behavior:

- `/media/nas` 未挂载或不可访问则失败。
- 源路径不存在则失败。
- `rsync` 失败或目标目录为空则失败。
- 不删除源数据。
- 默认不复用同一 `run_id` 目的目录，避免混淆。

---

### `module_control.py`

#### `switch_to_playback_mode(context: RunContext, config: ToolConfig) -> StepResult`

Required actions:

```text
soc1 stop: Camera, Canbus
soc2 stop: Camera, Driver-GNSS, Driver-LiDAR, Driver-NTRIP
soc2 start: Debug_Camera-Decode, Debug_Driver-LiDAR
```

默认命令形态：

```text
ssh nvidia@192.168.10.2 "sudo supervisorctl stop Camera"
ssh nvidia@192.168.10.2 "sudo supervisorctl stop Canbus"
ssh nvidia@192.168.10.3 "sudo supervisorctl stop Camera"
ssh nvidia@192.168.10.3 "sudo supervisorctl stop Driver-GNSS"
ssh nvidia@192.168.10.3 "sudo supervisorctl stop Driver-LiDAR"
ssh nvidia@192.168.10.3 "sudo supervisorctl stop Driver-NTRIP"
ssh nvidia@192.168.10.3 "sudo supervisorctl start Debug_Camera-Decode"
ssh nvidia@192.168.10.3 "sudo supervisorctl start Debug_Driver-LiDAR"
```

Artifacts:

```python
{
    "soc1_stopped": ["Camera", "Canbus"],
    "soc2_stopped": ["Camera", "Driver-GNSS", "Driver-LiDAR", "Driver-NTRIP"],
    "soc2_started": ["Debug_Camera-Decode", "Debug_Driver-LiDAR"]
}
```

Failure behavior:

- SSH 失败、timeout、supervisorctl 非 0 时失败。
- 默认遇到第一个失败模块命令即停止。
- 失败命令必须在日志中可见。
- MVP 不要求自动 rollback。

---

### `recorder.py`

#### `start_recorder(context: RunContext, config: ToolConfig) -> StepResult`

Output directory rule:

```text
/mdrive_data/bag/record_<YYYYMMDD>/<dataset_id>_<run_id>/
```

默认命令形态：

```text
ssh nvidia@192.168.10.3 "source ${MDRIVE_ROOT_DIR}/mdrive/setup.sh && (vmc list > /tmp/package_version.txt 2>&1 || true) && ${MDRIVE_ROOT_DIR}/mdrive/bin/mkit --dds_config /mdrive/mdrive_conf/dds/dds_flow.json --proto_lib /mdrive/mdrive/lib/libdata_proto_o.so,/mdrive/mdrive/lib/libchassis.src.proto.so record --config ${MDRIVE_ROOT_DIR}/mdrive_conf/modules/recorder/record_config.json --output <record_output_dir>/record.mcap"
```

Implementation note:

- 第一版直接使用原始 `mkit record` 命令，不通过 `supervisorctl` 封装的 Recorder。
- `record_config.json` 第一版保持不修改。
- `source setup.sh` 用于显式覆盖所需环境变量。
- 录制命令应以子进程方式启动，以便 orchestrator 能在 playback 后结束录制。

Artifacts:

```python
{
    "record_output_dir": "...",
    "recorder_host": "soc2",
    "record_pid": 12345
}
```

Failure behavior:

- 录制命令启动失败、输出目录无法确定或 PID 无法追踪则失败。

#### `stop_recorder(context: RunContext, config: ToolConfig) -> StepResult`

默认命令形态：

```text
ssh nvidia@192.168.10.3 "pkill -INT -f 'mkit.*record.*<record_output_dir>/record.mcap'"
```

Implementation note:

- Phase 3 需要在台架确认更稳妥的停止方式，例如基于 PID、session、还是信号。
- 若直接信号方式不可靠，可改为由启动包装脚本写 pidfile，再由 stop 阶段精准结束。

Artifacts:

```python
{
    "record_output_dir": "...",
    "generated_mcaps": ["..."]
}
```

Failure behavior:

- 停止失败则失败。
- 未找到 `.mcap` 文件则失败，除非后续明确增加 inspection-only debug 语义。

---

### `playback.py`

#### `play_once(context: RunContext, config: ToolConfig) -> StepResult`

当前 bench 约定命令基础形态：

```text
mkit play -c \
  /sensor/gnss/raw /sensor/gnss /sensor/gnss/gpgga /sensor/cors/rtcm \
  /sensor/ins /sensor/imu /sensor/imu/calib_state /sensor/lidar/scan \
  camera1 camera4 camera2 camera3 camera5 camera6 camera7 camera81 camera82 camera83 camera84 \
  /vehicle/highfreq /vehicle/lowfreq \
  -f <file_glob>
```

Contract:

- topic 列表必须集中配置在 `ToolConfig.playback_topics`。
- 输入必须支持文件通配符匹配。
- MVP 明确禁止 `-l`。
- 在执行前必须有显式 guard 拒绝 `-l` / `--loop`。

Artifacts:

```python
{
    "local_dataset_path": "...",
    "topics": ["..."],
    "loop_enabled": False
}
```

Failure behavior:

- `local_dataset_path` 缺失则失败。
- topic 为空则失败。
- 含 loop 标志则直接失败。
- `mkit play` 非 0 或超时则失败。

---

### Playback / Recording Coordination Contract

MVP 编排顺序固定为：

```text
start_recorder
playback once
stop_recorder
```

Rationale:

- 可能会录到少量空白前后边界，但能避免录到循环重复数据。
- 比“严格同步双进程起止”更简单、更安全。

Failure behavior:

- 若 `start_recorder` 成功但 `playback` 失败，`orchestrator.py` 仍必须尝试执行 `stop_recorder` 做清理，然后将主失败步骤记为 `playback`。

---

### `metadata.py`

#### `collect_metadata(context: RunContext, config: ToolConfig) -> StepResult`

Commands:

```text
vmc list || true
mkit info <mcap_path>
```

Artifacts:

```python
{
    "version_info": "...",
    "mcap_info": {
        "<mcap_path>": "<mkit info output>"
    },
    "generated_mcaps": ["..."]
}
```

Failure behavior:

- 没有生成 `.mcap` 则失败。
- 任一 `mkit info` 失败则失败。

---

### `result_store.py`

#### `create_run_context(dataset: DatasetEntry, packages: List[PackageSpec], config: ToolConfig) -> RunContext`

Run 目录规则：

```text
/mdrive_data/bench_smoke_runs/<YYYYMMDD>/<dataset_id>_<HHMMSS>_<short_uuid>/
```

期望文件布局：

```text
run_context.json
steps/
  01_install_versions.json
  02_prepare_data.json
  ...
commands.log
run.log
summary.json
summary.txt
```

#### `save_context(context: RunContext) -> None`

#### `save_step_result(context: RunContext, step: StepResult) -> str`

#### `write_summary(summary: RunSummary) -> None`

Contract:

- JSON 输出必须稳定到足以支持后续 HTML/NAS/算法验证集成。
- Text summary 要能直接在台架终端阅读。

---

### `orchestrator.py`

#### `run_full(dataset: DatasetEntry, packages: List[PackageSpec], config: ToolConfig) -> RunSummary`

一键模式步骤顺序：

```text
  1. install_versions
  2. prepare_data
  3. switch_modules
  4. playback
  5. start_recorder
  6. stop_recorder
  7. collect_metadata
  8. summarize
```

Failure behavior:

- 默认 fail-fast。
- 例外：playback 失败但 Recorder 已启动时，要尝试 stop_recorder 清理。
- 只要 run context 已存在，就必须尽量写出最终 summary。

#### `run_many(datasets: List[DatasetEntry], packages: List[PackageSpec], config: ToolConfig) -> List[RunSummary]`

Failure behavior:

- 数据集之间相互独立。
- 默认第一个失败数据集就停止整批执行；后续如需要，可额外设计 `--continue-on-dataset-failure`。

#### `run_debug_step(step: str, dataset: DatasetEntry, packages: List[PackageSpec], config: ToolConfig, run_id: Optional[str]) -> StepResult`

Failure behavior:

- 必须校验最小前置条件，而不是猜测：
  - `prepare_data` 需要有效 dataset
  - `switch_modules` 需要有效 config
  - `playback` 需要 `local_dataset_path`
  - `stop_recorder` / `collect_metadata` 需要已知 `record_output_dir`

---

## 5. Data Flow

### One-click mode

1. **CLI 接收参数**  
   用户运行 `bench-smoke run`，传入 manifest、dataset ID、多个安装包版本和可选 config。

2. **读取 manifest 并选择数据集**  
   `manifest.load_manifest()` 读取清单，`manifest.select_datasets()` 选出目标数据；字段缺失或 ID 不存在时提前失败。

3. **创建 run context**  
   `result_store.create_run_context()` 创建唯一路径和运行上下文，并写出初始 `run_context.json`。

4. **版本检查与安装**  
   `versioning.install_versions()` 在 soc1 上按一组版本组合依次执行 `md install <version>`，全部安装完成后执行 `md start`，并记录安装前后版本信息摘要。

5. **数据本地化**  
   `data_prep.prepare_dataset()` 先校验 `/media/nas` 已挂载，再校验源路径，并通过 `rsync` 将数据从数据集清单路径拷到 `/mdrive_data/base_test/...` 下的 run 专属目录。

6. **模块切换**  
   `module_control.switch_to_playback_mode()` 通过 SSH 分别控制 soc1/soc2 的模块停启；任一命令失败立即终止流程。

7. **启动录制**  
   `recorder.start_recorder()` 准备输出目录并在 soc2 直接启动 `mkit record` 进程。

8. **单次回灌**  
   `playback.play_once()` 基于本地数据路径和固定 topic 列表执行单次 `mkit play`，支持文件通配符输入，并显式拒绝 loop 模式。

9. **停止录制并发现产物**  
   `recorder.stop_recorder()` 停止 `Recorder`，并发现生成的 `.mcap`。

10. **元数据采集**  
    `metadata.collect_metadata()` 执行版本信息采集命令、对每个 `.mcap` 跑 `mkit info`，并记录路径与输出。

11. **生成最终汇总**  
    `result_store.write_summary()` 写出 `summary.json` 与 `summary.txt`。

### Debug step mode

1. 用户运行 `bench-smoke debug <STEP> ...`。
2. CLI 加载 manifest/config，并新建或加载已有 `run_context`。
3. `orchestrator.run_debug_step()` 检查目标步骤前置条件。
4. 目标 step 经由 `step_runner.run_step()` 执行。
5. step result 落盘。
6. CLI 返回该单步的成功/失败结果。

Debug 模式和一键模式必须复用同一套 step module，不允许 duplicate command-building 逻辑。

---

## 6. Key Design Decisions and Rationale

### Decision 1: 本地 CLI，而不是服务架构

环境离线、使用者是开发和测试、运行位置是 bench 本机，因此本地 Python CLI 比服务化方案更易部署、更易排障，也更符合 MVP。但模块边界和结果产物格式需要保持清晰，便于后续如有需要转向服务化架构。

### Decision 2: 按物理动作拆分 step module，由中央 orchestrator 编排

版本安装、数据准备、模块控制、录制、回灌、元数据采集分别独立成模块，后续 Phase 3 可按模块并行委派；顺序和清理策略只保留在 `orchestrator.py`。

### Decision 3: 一键模式和 Debug 模式共享同一执行引擎

两种模式必须走相同 step contract，否则 debug 行为很快会和正式流程漂移。

### Decision 4: 默认 fail-fast

安装失败、数据未准备好、模块未切换完成时继续执行会生成误导性结果，因此关键步骤默认失败即停。唯一例外是 playback 失败后仍需尝试 stop recorder 清理。

### Decision 5: 单次回灌由 playback 模块强约束

“避免录入循环重复数据”优先级最高，因此 loop flag 不能靠操作者自觉，必须由代码显式 guard。

### Decision 6: 录制先启动，回灌后停止

MVP 不追求毫秒级精确同步，而优先保证简单可实现、逻辑可解释和不录到循环数据。即使多录到少量边界空白，也优于引入复杂双进程同步。录制默认直接调用底层 `mkit record`，而不是依赖 `supervisorctl` 的封装。

### Decision 7: 结构化 JSON + 人类可读文本总结

JSON 用于后续 HTML/NAS/算法验证扩展；text summary 用于 bench 终端直接查看。

### Decision 8: 所有 subprocess 统一收口到 `command_runner.py`

统一 timeout、日志、stdout/stderr、返回码处理，可以减少 Phase 3 的重复实现，并为未来 dry-run / replay 做准备。

### Decision 9: Bench 细节放配置，不上插件系统

soc 地址、端口、模块名、topic、timeout 等都属于配置维度；MVP 引入插件系统只会拖慢落地。

### Decision 10: 未来扩展只保留接口，不进入 MVP 路径

HTML 报告、NAS 上传、算法验证通过稳定产物格式预留扩展点，但不参与第一版主流程。

---

## 7. DRI Assignment

| DRI Label | Module/Area | Responsibility |
|---|---|---|
| DRI-CLI | `cli.py` | 命令行体验、参数校验、退出码、模式分发 |
| DRI-Config | `config.py` | 默认值、配置加载、路径/超时/模块/topic/包列表校验 |
| DRI-Models | `models.py` | 共享 dataclass、enum、序列化兼容性 |
| DRI-Manifest | `manifest.py` | manifest 解析、字段校验、数据集选择 |
| DRI-Orchestrator | `orchestrator.py` | 全流程顺序、debug 单步分发、fail-fast 与 cleanup 策略 |
| DRI-StepRunner | `step_runner.py` | step 生命周期记录、异常归一化、step 结果落盘 |
| DRI-CommandRunner | `command_runner.py` | 本地/远程命令执行、timeout、stdout/stderr 捕获 |
| DRI-Versioning | `versioning.py` | `md install` / `md start`、多版本安装、版本前后记录 |
| DRI-DataPrep | `data_prep.py` | manifest 数据源 → `/mdrive_data/base_test` 的 `rsync` 本地化与校验 |
| DRI-ModuleControl | `module_control.py` | soc1/soc2 的 SSH 模块停启 |
| DRI-Recorder | `recorder.py` | `mkit record` 启停、输出目录、`.mcap` 发现 |
| DRI-Playback | `playback.py` | 单次 `mkit play`、topic 处理、loop 禁止 |
| DRI-Metadata | `metadata.py` | `mkit info`、最终 `vmc list`、输出元数据采集 |
| DRI-ResultStore | `result_store.py` | run 目录、JSON/text summary、可追溯产物 |
| DRI-Logging | `logging_setup.py` | 终端/文件日志初始化 |
| DRI-Extensions | `extensions/*` | 未来 report/upload/validation 扩展缝 |

---

## 8. Risks and Open Questions

1. **`mkit play` 的精确输入形式**  
   已确认输入为文件，且需要支持通配符；是否还需要额外参数，仍可在台架上确认。  
   **影响模块**：`playback.py`

2. **录制停止方式的稳妥性**  
   已确认输出路径可由原始 `mkit record --output` 显式控制，但停止录制时应采用 pid、信号还是包装脚本，仍需在台架上确认。  
   **影响模块**：`recorder.py`

3. **SSH 密码注入方案**  
   用户已提供密码，但实现时不能把密码散落在多个业务模块里，需要在 `command_runner.py` 或统一配置入口收口。  
   **影响模块**：`command_runner.py`, `config.py`

4. **`Debug_Driver-LiDAR` 名称是否精确无误**  
   该 supervisor 模块名看起来可能有拼写敏感风险，需在台架上确认。  
   **影响模块**：`module_control.py`

5. **supervisorctl 对 already stopped/started 的返回行为**  
   需要确认模块已停/已起时命令是成功还是失败，以便决定是否实现幂等判定。  
   **影响模块**：`module_control.py`

6. **`md install` 的版本组合映射规则**  
   已确认用户输入的是一组版本组合，其中 `mdrive` 与 `mdrive_conf` 为核心包，地图包可选；但 CLI 是否直接收 2~3 个显式参数，还是收一个组合文件，仍可在实现前最终确定。  
   **影响模块**：`cli.py`, `versioning.py`

7. **超时默认值**  
   已知 `md install` 由工具自动处理；`rsync` 网络千兆、单包约 500MB / 15s；`mkit play` / `record` 启停可先按 0.5s 起步，但仍需结合台架实测收敛默认值。  
   **影响模块**：`config.py`

8. **Debug 模式是否允许复用已拷贝数据**  
   已确认第一版默认不复用，避免 run 结果混淆；如果 bench 频繁调试，后续可能需要 `--reuse`。  
   **影响模块**：`data_prep.py`, `orchestrator.py`
