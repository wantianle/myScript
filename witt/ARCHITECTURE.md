# Witt 架构说明

## 文档目的

本文档用于描述当前 `witt` 的整体结构、模块边界、异常流、模型边界和后续演进方向。

目标不是写成“百科全书”，而是提供一套足够清晰、可落地、可持续维护的约束，避免后续开发再次把代码堆回“流程脚本 + 到处塞逻辑”的状态。

## 运行约束

- Python 基线版本：`3.8`
- 新代码默认必须兼容 Python 3.8
- 避免使用 Python 3.9+/3.10+ 才支持的语法
  - 不使用 `list[str]`
  - 不使用 `dict[str, int]`
  - 不使用 `X | Y`
- 优先使用：
  - `typing.List`
  - `typing.Dict`
  - `typing.Tuple`
  - `typing.Optional`
  - `typing.Union`

## 分层设计

### `interface/`

负责终端交互、用户提示和用例级流程编排。

- [ui.py](/home/mini/dev/myScript/witt/interface/ui.py)
  - 只负责展示
  - 输出 banner、状态、列表、播放信息
  - 不承载业务逻辑

- [prompter.py](/home/mini/dev/myScript/witt/interface/prompter.py)
  - 通用 prompt 基础层
  - 负责通用文本输入、确认输入、菜单选择、公共输入辅助函数

- [config_prompter.py](/home/mini/dev/myScript/witt/interface/config_prompter.py)
  - 配置输入层
  - 负责采集：
    - 车辆
    - 日期
    - 切片时间窗
    - 数据源路径
    - 导出路径
    - 版本文件路径

- [replay_prompter.py](/home/mini/dev/myScript/witt/interface/replay_prompter.py)
  - 回播专用输入层
  - 负责：
    - 回播条目选择
    - SOC 选择
    - 回播时间范围输入
    - 手动回播路径输入

- [channel_prompter.py](/home/mini/dev/myScript/witt/interface/channel_prompter.py)
  - Channel 过滤专用输入层
  - 负责：
    - 聚合可选频道
    - 勾选删除频道

- [workflow.py](/home/mini/dev/myScript/witt/interface/workflow.py)
  - 主流程编排
  - 负责“查询 -> 选 Tag -> 切片 -> 下载 -> 可选回播”
  - 应保持精简，只负责用例编排

- [replay_workflow.py](/home/mini/dev/myScript/witt/interface/replay_workflow.py)
  - 回播编排层
  - 负责：
    - 环境恢复
    - 标准回播
    - 红绿灯回灌回播
    - 回播前准备

- [cli.py](/home/mini/dev/myScript/witt/interface/cli.py)
  - 顶层入口
  - 负责菜单循环和顶层异常捕获

### `core/`

负责核心业务、执行适配、会话状态和领域模型。

- [models.py](/home/mini/dev/myScript/witt/core/models.py)
  - 领域模型和原始边界 schema
  - 优先承接：
    - 模型构造
    - 缓存结构转换
    - metadata 转换
    - 配置对象构造

- [errors.py](/home/mini/dev/myScript/witt/core/errors.py)
  - 核心层异常定义
  - `core/` 不直接打印 UI 提示，而是抛出结构化异常

- [context.py](/home/mini/dev/myScript/witt/core/context.py)
  - 会话级上下文
  - 负责：
    - 配置加载
    - 工作目录计算
    - 临时目录
    - 环境变量组装
    - logger 初始化

- [session.py](/home/mini/dev/myScript/witt/core/session.py)
  - 应用装配根
  - 负责：
    - 组合 `context + runtime + engine + adapter`
    - 决定当前使用 docker 还是 ssh 执行通道
  - `session.runtime` 是主运行时协调入口

- [runner.py](/home/mini/dev/myScript/witt/core/runner.py)
  - 运行时编排服务
  - 负责：
    - 协调查询、环境恢复、回放栈启动等执行入口
    - 将底层异常转换为上层可消费的结构化错误
    - 保留少量开发环境脚本调用能力
  - 不负责 prompt，不负责 UI

- `adapter/`
  - 执行通道适配器
  - [docker.py](/home/mini/dev/myScript/witt/core/adapter/docker.py)
  - [ssh.py](/home/mini/dev/myScript/witt/core/adapter/ssh.py)
  - 只处理：
    - 命令执行
    - 路径映射
    - 文件拉取

- `engine/`
  - 业务服务层
  - [downloader.py](/home/mini/dev/myScript/witt/core/engine/downloader.py)
    - 批次规划
    - 文件切片/同步
    - 元数据输出
  - [record_finder.py](/home/mini/dev/myScript/witt/core/engine/record_finder.py)
    - tag 解析
    - record 索引构建
    - 时间窗匹配
    - 查询结果 manifest 输出
  - [record_query.py](/home/mini/dev/myScript/witt/core/engine/record_query.py)
    - 本地 / NAS / 远程查询编排
    - 远程路径发现与 tag 文本读取
  - [player.py](/home/mini/dev/myScript/witt/core/engine/player.py)
    - 回放库加载
    - 回放计划构建
  - [runtime_env.py](/home/mini/dev/myScript/witt/core/engine/runtime_env.py)
    - version 文件解析
    - vmc.sh 环境同步
  - [replay_stack.py](/home/mini/dev/myScript/witt/core/engine/replay_stack.py)
    - 标准回放栈启动
    - 红绿灯回灌栈启动
  - [recorder.py](/home/mini/dev/myScript/witt/core/engine/recorder.py)
    - record 信息解析
    - record split

## Shell 依赖边界

当前项目已经把核心业务逻辑大部分迁回 Python，但仍保留少量 shell 作为环境与部署辅助。

### 已 Python 化的核心链路

- Record 查询
  - 由 [record_query.py](/home/mini/dev/myScript/witt/core/engine/record_query.py) 和 [record_finder.py](/home/mini/dev/myScript/witt/core/engine/record_finder.py) 负责
  - 已不再依赖 `find_record.sh`

- 运行环境恢复
  - 由 [runtime_env.py](/home/mini/dev/myScript/witt/core/engine/runtime_env.py) 负责
  - 已不再依赖 `restore_runtime_env.sh`

- 回放工具栈启动
  - 由 [replay_stack.py](/home/mini/dev/myScript/witt/core/engine/replay_stack.py) 负责
  - 已不再依赖 `start_replay_stack.sh` 和 `start_traffic_light_stack.sh`

### 仍保留 shell 的部分

- 开发环境初始化和安装
  - [setup.sh](/home/mini/dev/myScript/witt/scripts/setup.sh)
  - [vmc_deploy.sh](/home/mini/dev/myScript/witt/scripts/vmc_deploy.sh)
  - [vmc.sh](/home/mini/dev/myScript/witt/scripts/vmc.sh)

- 开发容器辅助入口
  - `RuntimeCoordinator.run_docker()`
  - `RuntimeCoordinator.into_docker()`
  - 仍通过 `dev_start.sh` / `dev_into.sh` 一类环境脚本完成

### 当前原则

- 业务规则优先留在 Python
- 安装、部署、开发环境拉起一类系统操作允许继续保留 shell
- 若 shell 开始承载业务判断、状态机或复杂文本解析，应优先迁回 Python

### `utils/`

纯工具函数层。

- [parser.py](/home/mini/dev/myScript/witt/utils/parser.py)
  - 负责：
    - 文本解析
    - manifest 解析
    - 时间范围解析
    - record 文件排序
  - 不负责终端流程控制

## 领域模型边界

当前已经抽出来并应优先复用的对象如下。

### 任务和主流程对象

- `TaskEntry`
  - 来自 `manifest`
  - 用于 workflow、downloader、channel 选择

### 配置对象

- `AppConfig`
- `HostConfig`
- `RemoteConfig`
- `DockerConfig`
- `PathsConfig`
- `LogicConfig`

使用方式应优先为：

```python
ctx.host.dest_root
ctx.remote.ip
ctx.docker.container
ctx.paths.scripts_dir
ctx.logic.before
```

而不是：

```python
ctx.config["host"]["dest_root"]
ctx.config["logic"]["before"]
```

### 回播对象

- `ReplayRecord`
- `LibraryEntry`
- `PlaybackPlan`
- `LibraryLoadResult`
- `RecordInfo`
- `ChannelInfo`

### 元数据对象

- `TagInfo`
- `RecordMeta`

`meta.json` 的读写应通过 `RecordMeta` 和 `TagInfo` 完成，而不是手拼字典。

## 原始边界 Schema

[models.py](/home/mini/dev/myScript/witt/core/models.py) 中的 `TypedDict` 用来描述“原始数据边界”。

适用场景：

- YAML 配置加载后的原始字典
- JSON 缓存读取后的原始字典
- `meta.json` 读取后的原始字典

原则：

- 应用内部优先使用 dataclass
- 文件/缓存/外部原始结构优先使用 TypedDict
- 不要让 `Dict[str, Any]` 到处流转

## 异常处理规则

- `core/` 层不直接调用 `ui.print_status(...)`
- `core/` 层抛出结构化异常
- `interface/` 层决定：
  - 这是 `WARN` 还是 `ERROR`
  - 是否继续流程
  - 如何展示给用户

推荐做法：

- 让异常自然向上传播
- 或使用：

```python
raise SomeError("...") from e
```

避免：

```python
except Exception as e:
    raise e
```

因为这类写法：
- 不增加信息
- 只是制造噪音
- 让异常流更难读

## 命名规则

### 对象命名

优先用名词：

- `TaskEntry`
- `ReplayRecord`
- `RecordMeta`
- `ChannelInfo`

### 动作命名

优先用动词短语：

- `load_library`
- `build_playback_plan`
- `plan_download`
- `restore_runtime_environment`

### 变量命名

优先明确语义，不要偷懒用一字母：

- `task_entry` 优于 `t`
- `replay_record` 优于 `r`
- `channel_name` 优于 `name`
- `file_path` 优于 `p`

## 函数契约规则

公共函数应优先具备：

- 明确的返回类型
- 简短但有效的 docstring
- 清晰的输入/输出语义

原则：

- helper 返回 typed object 优于裸 dict
- public API 返回值尽量稳定
- 避免“有时返回对象，有时返回字符串，有时返回 False”这种风格

## 测试策略

当前测试策略是“先薄后厚”。

优先覆盖：

1. `core/models.py`
2. `utils/parser.py`
3. 纯逻辑 helper
4. 小型 workflow 辅助逻辑

暂时不优先：

- docker/ssh 这类强依赖外部环境的集成测试
- 大量 shell 脚本驱动的端到端测试

原因很简单：
- 先把纯逻辑层的护栏建起来，性价比最高

当前已有：

- [tests/test_models_parser.py](/home/mini/dev/myScript/witt/tests/test_models_parser.py)

后续建议继续补：

- `RecordMeta` merge/update 逻辑
- `LibraryEntry` metadata 构造逻辑
- `downloader.plan_download()`
- replay 选择逻辑

## 当前建议的工程化路线

下面是一套更系统、可执行的后续路线，而不是零碎补丁。

### 第一阶段：边界稳定

目标：先让“东西应该放哪里”变清楚。

已完成的大方向：

- prompt 已按用途拆分
- replay workflow 独立
- core 层不直接做 UI 输出
- task/replay/config/meta 已逐步对象化

后续要继续坚持：

- 新功能先判断属于哪一层
- 不要图快直接往已有流程函数里塞逻辑

### 第二阶段：模型优先

目标：减少散乱 dict 和手拼 schema。

建议：

- 新增业务数据时，先建 dataclass
- 若存在文件/缓存边界，再补 TypedDict
- 模型负责：
  - `from_xxx`
  - `to_xxx`
  - 结构归一化

而不是：

- 在 `player/parser/downloader` 里到处复制粘贴对象装配

### 第三阶段：异常体系继续统一

当前已建立 `core/errors.py`，但还可以继续推进：

- 用更明确的领域异常替代泛化 `RuntimeError`
- 区分：
  - 用户输入错误
  - 环境错误
  - 外部依赖错误
  - 数据损坏错误

收益：

- workflow 决策更清楚
- 错误提示更一致
- 日志与用户提示更容易分层

### 第四阶段：服务层瘦身

目标：让 service 真正只做 service。

例如：

- `player`
  - 只负责构建回放计划和加载回放库
- `downloader`
  - 只负责下载/切片/结果汇总
- `workflow`
  - 只负责编排

不要让 service 同时承担：

- schema 细节
- prompt 细节
- UI 展示

### 第五阶段：测试护栏完善

目标：在继续重构前给关键模型和逻辑加护栏。

建议优先级：

1. `models`
2. `parser`
3. `downloader.plan_download`
4. `RecordMeta/LibraryEntry`
5. `replay selection`

经验上：

- 每完成一轮模型重构
- 都应补至少一条覆盖新增边界的测试

### 第六阶段：脚本治理

当前 shell 脚本仍然是重要执行入口，这没问题。

但后续建议逐步梳理：

- 哪些脚本只是稳定的外部包装，继续保留
- 哪些脚本已经在承载业务逻辑，适合迁到 Python

建议顺序：

1. 先稳定边界
2. 再迁移脚本

不要反过来。

### 第七阶段：文档和规范常态化

建议以后保持：

- 架构文档用中文
- 新模型和新 workflow helper 尽量补短注释
- 新增重要边界时，顺手更新文档

不要等“代码乱了”再补文档。

## 未来改动前的自检问题

以后你自己改功能前，可以先问自己这几个问题：

1. 这段逻辑属于哪一层？
2. 我是不是又在传裸 dict 了？
3. 这个函数有没有稳定的输入/输出契约？
4. 这个异常应该在 core 处理还是 interface 处理？
5. 这次改动要不要顺手补一条测试？

如果这五个问题都能答清楚，代码基本就不容易重新滑回屎山。 
