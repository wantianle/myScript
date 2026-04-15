# Witt 阶段性总结（2026-04-15）

## 一、系统性总述

这一阶段的工作不是单点修补，而是围绕两个目标同步推进：

1. 先把已经影响使用体验和稳定性的实际问题修掉
2. 再把项目从“流程往上堆”的状态，逐步拉回到“分层明确、边界清晰、可持续维护”的工程化结构

整体来看，这一阶段已经完成了从“脚本式工具”向“有明确模型和边界的工程项目”的过渡。主要成果可以归纳为四条主线：

- 功能和体验类问题得到修复
  - 主菜单快捷序号错乱问题修复
  - README 回放命令时间点计算修复
  - setup/venv 安装流程稳定性改进
  - 红绿灯回灌入口从 demo 形态升级为正式流程

- 交互层与核心层分离
  - `ui / prompter / workflow / replay_workflow` 职责明显收清
  - `core` 不再直接承担用户提示

- 核心数据结构显式化
  - `TaskEntry / ReplayRecord / LibraryEntry / RecordInfo / RecordMeta / AppConfig` 等核心对象已建立
  - 原始边界从散乱 `dict` 收敛为 `TypedDict`

- 测试和文档开始成型
  - 已补上 models、parser、downloader planning、repository、config/context 等关键最小测试
  - 已补充中文架构说明和贡献指南

从工程角度判断，这一阶段的目标已经达成：代码已经不再是“到处塞逻辑”的不稳定状态，而是拥有了后续继续开发功能所需的基本骨架。

---

## 二、详细变更说明

### 1. 已完成的缺陷修复

这一阶段先处理了一批会直接影响日常使用的问题：

- 修复主菜单快捷序号错乱
  - 问题根因是 `questionary.Choice` 对象被跨循环复用，导致快捷键分配状态残留
  - 处理方式是改成每轮菜单都重新构造菜单项，并同步把 `menu_map` 放回循环内

- 修复 README 中 `cyber_recorder play -s` 时间点异常
  - 原本 `-s` 的计算在 `before/after` 异常组合下会超出切片有效时长
  - 现已改为带边界约束的更合理计算方式，避免出现和切片定义不一致的起点

- 修复 setup 中 venv 自动安装链路
  - 之前 `apt-get update && apt-get install ...` 容易被第三方源报错短路
  - 现已补上更稳的 `venv` 检测和回退安装逻辑

- 修复 channel prompt 的参数签名问题
  - 之前 `Callable[[str, bool], bool]` 的调用方式与实际参数不一致
  - 已修复为显式传入默认值

- 修复一批 IDE 静态报错
  - `TypedDict` 必需键定义
  - `datetime` 参数类型不匹配
  - 测试桩对象类型不匹配
  - `Optional` 下标访问

- 修复全量模式入口和选择逻辑
  - 原实现把“切片还是全量”放在 Tag 选择之后，且播完后只能顺序播下一个
  - 现已调整为：
    - 先选模式
    - 全量模式下每轮重新展示查询得到的 Tag 列表
    - 用户可反复选择任意 Tag 进行原始数据回放

### 2. 回放/回灌主线的解耦

这一阶段最重要的一条重构主线，是把回放相关流程从一团混合逻辑中拆开：

- `player.play()` 中原本同时承担：
  - 播放命令构造
  - 环境恢复
  - 工具启动
  - 输出展示

  现在已经拆开：
  - `player` 只负责“回放库加载”和“回放计划构建”
  - `workflow/replay_workflow` 负责回放前准备
  - `ui` 负责展示

- `replay_workflow.py` 已独立出来
  - 现在专职处理：
    - 标准回放
    - 红绿灯回灌回放
    - 环境恢复
    - 回放前准备

- 红绿灯回灌流程从原来的 demo 入口升级为正式编排流程
  - 支持自动/手动两条入口
  - 不再“挂靠在普通回放流程里”

- 全量模式已经正式落地
  - 不切片
  - 不移动原始包
  - 不生成导出目录
  - 直接基于 `find_record.sh` 的结果构造 `-b/-e` 原始数据回放
  - 仍复用现有环境恢复和工具链启动流程

### 3. prompt 分层的重构

原来的 `prompter.py` 过于臃肿，这一阶段已经把交互按用途拆分：

- `prompter.py`
  - 通用 prompt 基础层

- `config_prompter.py`
  - 配置输入

- `replay_prompter.py`
  - 回播交互

- `channel_prompter.py`
  - Channel 过滤交互

这样之后：
- `cli` 更薄
- `workflow` 更像编排层
- prompt 不再全部堆在一个文件中

### 4. 数据模型和原始 schema 的规范化

这一阶段已经逐步把高频业务对象从散乱 `dict` 拉成显式 dataclass：

- 流程对象
  - `TaskEntry`

- 回播对象
  - `ReplayRecord`
  - `LibraryEntry`
  - `RecordInfo`
  - `ChannelInfo`

- 元数据对象
  - `TagInfo`
  - `RecordMeta`

- 配置对象
  - `LogicConfig`
  - `HostConfig`
  - `RemoteConfig`
  - `DockerConfig`
  - `PathsConfig`
  - `AppConfig`

同时，把这些对象在文件边界上的“原始结构”统一定义成了 `TypedDict`，用于：

- YAML 原始配置
- `meta.json`
- `local_library.json`

这一步的收益非常明显：

- IDE 能更好提示
- 修改字段时更容易集中改
- 调用层不再到处传裸 `dict`

### 5. repository 边界抽取

原来 `player/downloader` 里还在直接做：

- `meta.json` 读写
- `local_library.json` 读写

现在已经抽成：

- `MetadataRepository`
- `LibraryCacheRepository`

并且进一步把 repository 的装配统一回收到了 `AppSession`，不再由 service 自己创建依赖。

这意味着：

- service 更纯
- 装配边界更清楚
- 测试时更容易注入替身

### 6. 测试护栏建设

这一阶段补上了第一批真正有价值的最小测试：

- `tests/test_models_parser.py`
  - parser 和核心模型转换

- `tests/test_downloader.py`
  - 下载规划行为

- `tests/test_repository.py`
  - repository 读写与扫描

- `tests/test_config_context.py`
  - 配置聚合和上下文状态

当前测试已经能覆盖：

- parser
- models
- metadata
- repository
- downloader planning
- config/context
- 全量模式原始回放记录构造

这对后续继续重构和做新功能都非常关键。

### 7. 文档和规范

这一阶段补了两份关键文档：

- [ARCHITECTURE.md](/home/mini/dev/myScript/witt/ARCHITECTURE.md)
  - 已改成中文
  - 包含分层、模型边界、异常策略、测试策略和后续路线

- [AGENTS.md](/home/mini/dev/myScript/witt/AGENTS.md)
  - 面向贡献者的仓库说明

这两份文档的意义不是“补材料”，而是给后续开发提供一致的约束，避免边界再次被踩坏。

---

## 三、这一阶段的工程化收获

如果要提炼成几条真正值得记住的工程化经验，这一阶段最关键的是：

### 1. 先分层，再加功能

以前的问题不是功能不会写，而是新功能来了不知道该放哪，所以自然就往已有流程里塞。

现在已经逐步建立起一个更清楚的层次：

- 展示：`ui`
- 交互：`prompter/*`
- 编排：`workflow/*`
- 核心业务：`core/engine`
- 执行通道：`core/adapter`
- 边界持久化：`core/repository`
- 领域对象：`core/models`

这是这个阶段最值的一件事。

### 2. 模型先行，比到处传 dict 稳定得多

一旦模型稳定下来：

- IDE 提示会更好
- 重构范围更集中
- 语义更清楚
- 测试也更好写

### 3. 让 service 只做 service

这一阶段持续在做的事，本质上都是：

- 不让 `service` 管 prompt
- 不让 `service` 管 UI
- 不让 `service` 管文件格式细节

这会让 service 更适合长期扩展。

### 4. 测试不需要一开始很多，但必须覆盖关键边界

先补最值的纯逻辑测试，比空喊“以后再加测试”要有用得多。

---

## 四、下一个阶段的建议规划

现在这阶段已经基本完成，下一阶段我建议把重点从“持续无止境纯重构”切到“在稳定底座上做有价值的扩展”。

建议顺序如下：

### 1. 功能优先回归

优先回到你真正关心的功能演进：

- 全量模式体验继续完善
- 回灌/回播流程优化
- setup/docker 使用体验改进

原因是：
- 目前骨架已经足够支撑功能开发
- 继续纯重构的收益会开始递减

### 2. 测试继续补，但只补高价值边界

后续建议补：

- `replay_workflow`
- `channel_prompter`
- `config_prompter`
- `player.build_playback_plan`

仍然坚持“小而有价值”的测试策略，不建议一下上重型集成测试。

### 3. 清剩余的质量尾巴

可以在功能开发的同时，顺手清理：

- 少量还偏宽的类型签名
- 少量重复的异常包装
- 少量缺少短 docstring 的公共 helper

但不建议为了这些再单独开太长的纯重构周期。

### 4. 观察 shell 脚本是否值得迁移

现在 shell 仍然承担不少执行职责。

建议不是立刻全迁移，而是观察：

- 哪些脚本只是稳定的包装层
- 哪些脚本已经承载越来越多业务逻辑

只有后者，才值得在后续逐步迁入 Python。

### 5. 文档保持同步

后续再改动大边界时，建议同步更新：

- [ARCHITECTURE.md](/home/mini/dev/myScript/witt/ARCHITECTURE.md)
- [AGENTS.md](/home/mini/dev/myScript/witt/AGENTS.md)

这样文档才能真正成为长期维护工具，而不是某一晚的产物。

---

## 五、结论

这一阶段的工作，已经把项目从“容易越改越堆”的状态，拉到了“可以在工程化底座上继续做功能”的状态。

所以，下一个阶段最合理的策略不是继续无限制纯重构，而是：

- 以功能需求为主
- 以测试和小步收口为辅
- 在新增功能时继续遵守本阶段建立起来的边界和规范

---

## 六、阶段完成清单

为了便于后续回顾，这里给出本阶段已经完成的工程化清单。

### 已完成的结构治理

- `ui / prompt / workflow / core / utils` 分层已基本稳定
- `replay_workflow` 已从主流程中拆出
- `replay_prompter / channel_prompter / config_prompter` 已拆出
- `core` 不再直接承担 UI 提示
- `repository` 层已建立并投入使用

### 已完成的数据结构规范化

- `TaskEntry`
- `ReplayRecord`
- `LibraryEntry`
- `ChannelInfo`
- `RecordInfo`
- `TagInfo`
- `RecordMeta`
- `AppConfig`
- `HostConfig`
- `RemoteConfig`
- `DockerConfig`
- `PathsConfig`
- `LogicConfig`

### 已完成的边界规范化

- `meta.json` 读写已走 `RecordMeta`
- `local_library.json` 读写已走 `LibraryCacheRepository`
- 配置已走 `AppConfig` 聚合根
- 原始边界 schema 已用 `TypedDict` 描述

### 已完成的质量护栏

- 模型/解析测试
- 下载规划测试
- repository 测试
- 配置与上下文测试
- 全量 unittest 已通过

### 已完成的文档

- [ARCHITECTURE.md](/home/mini/dev/myScript/witt/ARCHITECTURE.md)
- [AGENTS.md](/home/mini/dev/myScript/witt/AGENTS.md)
- [STAGE_SUMMARY_20260415.md](/home/mini/dev/myScript/witt/STAGE_SUMMARY_20260415.md)

### 建议的阶段收尾结论

这阶段建议正式收口，不再继续无边界纯重构。

后续进入新阶段时，优先顺序应改成：

1. 功能开发
2. 为新功能补针对性测试
3. 只做必要的小步重构

如果继续长时间只做结构重构，收益会开始明显下降。 
- 以测试和小步收口为辅
- 在新增功能时继续遵守这阶段建立起来的边界和规范

如果照这个节奏推进，后面再扩功能，维护成本会低很多。 
