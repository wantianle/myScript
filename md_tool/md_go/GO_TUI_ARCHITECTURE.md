# md Go TUI 重构架构设计

## 目标

将当前 `md.sh` 从单文件 Bash 运维脚本重构为一个 Go 编写的统一终端工具。新工具以 TUI 为主入口，同时保留命令式 CLI 子命令，支持车端 Linux 环境运行，并能编译出跨平台二进制。

核心目标：

- 消除单文件脚本耦合，按业务域拆分模块。
- 去掉对 `fzf`、`less`、`rsync` 等交互和传输外部依赖。
- 保留对车端固有命令和环境的调用边界，例如 `systemctl`、`supervisorctl`、`dtop`、`mkit`、`vmc`。
- 将 tag、record 定位、导出、clip 等高风险逻辑变成可测试 Go 代码。
- 统一错误处理、超时、日志、进度和用户确认流程。

## 非目标

- 不在第一阶段替换所有车端系统命令。
- 不从零实现 `systemctl`、`supervisorctl`、`mkit`、`vmc` 的内部协议。
- 不在第一版实现完整 rsync 协议或块级增量同步。
- 不一次性删除 `md.sh`，重构期间 Bash 入口和 Go 入口并行。

## 运行形态

目标二进制名称继续使用 `md`，并支持 `tag` 软链接模式：

```text
md
  进入统一 TUI

md tag info <message>
md tag list
md tag exp --clip -d 20260606 -i 1 2
  非交互 CLI，用于脚本化调用

tag info <message>
tag list
tag exp ...
  与现有 tag 软链接兼容
```

TUI 是第一入口，但核心能力必须可以通过 CLI 调用。这样可以同时满足日常人工操作和自动化使用。

## 依赖替换方案

### fzf

使用 `Bubble Tea + Bubbles` 构建统一 TUI，列表筛选优先使用 `bubbles/list`。`bubbles/list` 已经提供过滤、分页、状态消息和帮助栏，适合承载文件选择、模块选择、tag 选择等交互。

必要时直接引入 `sahilm/fuzzy` 作为匹配算法，但不直接把它当 UI 使用。

不采用 `go-fuzzyfinder` 作为主方案。原因是它更适合快速替代单个 `fzf` 弹窗，而本项目目标是统一 TUI，需要把列表、预览、日志、状态、进度和任务执行放在同一个界面状态机里。

### less

使用 `bubbles/viewport` 实现只读滚动视图，用于查看日志、命令输出、tag 详情、导出结果等长文本内容。

基础能力：

- 上下滚动
- 半页滚动
- 跳到顶部/底部
- 自动跟随日志尾部
- 复制当前视图内容的提示

第一版不强制实现 `less` 的完整搜索能力。日志搜索可以作为后续增强。

### rsync

使用 `golang.org/x/crypto/ssh` 和 `github.com/pkg/sftp` 替代 `rsync` 的日常文件回传能力。

第一版支持：

- SSH 用户识别和交互输入
- 密钥认证
- 远端目录创建
- 单文件上传
- 目录递归上传
- 文件大小和修改时间检查
- 进度回调
- 失败重试

第一版不实现 rsync 差异块同步。mcap 文件通常是完整导出，稳定性和可诊断性优先于复杂增量。

### 外部命令保留边界

以下命令仍作为车端能力边界保留，通过统一 runner 调用：

- `systemctl`
- `supervisorctl`
- `journalctl`
- `mountpoint`
- `df`
- `dtop`
- `mkit`
- `vmc`
- `ssh-copy-id` 可作为过渡方案保留，后续可改为 Go 写入公钥流程

所有外部命令必须通过统一 `runner` 包执行，禁止业务模块直接调用 `exec.Command`。

## 目标目录结构

```text
md_tool/
  go-md/
    go.mod
    cmd/
      md/
        main.go
    internal/
      app/
        session.go
        routes.go
      cli/
        root.go
        tag.go
        record.go
        export.go
      tui/
        model.go
        theme.go
        keys.go
        pages/
          home.go
          tag.go
          export.go
          module.go
          log.go
      config/
        config.go
        defaults.go
      runner/
        runner.go
        local.go
        remote.go
      sshx/
        client.go
        auth.go
        knownhosts.go
      transfer/
        sftp.go
        progress.go
      tag/
        model.go
        store.go
        locator.go
        export.go
        clip.go
      vehicle/
        service.go
        recorder.go
        channel.go
        module.go
      disk/
        disk.go
        diagnose.go
        fix.go
      vmc/
        remote.go
        upgrade.go
        install.go
      logview/
        stream.go
        buffer.go
      errors/
        errors.go
    pkg/
      mcaplocator/
        locator.go
```

说明：

- `cmd/md` 只做入口。
- `internal/app` 负责装配依赖。
- `internal/cli` 负责非交互子命令。
- `internal/tui` 负责 Bubble Tea 页面和状态机。
- `internal/tag` 是第一阶段迁移重点。
- `internal/runner` 是所有本地和远程命令的统一执行层。
- `internal/transfer` 承载 SFTP 回传，不让业务模块直接依赖 SSH 细节。
- `pkg/mcaplocator` 只在 record 定位逻辑稳定且有复用价值后再开放。

## 分层边界

### CLI 层

负责：

- 参数解析
- 命令别名
- 非交互输出
- 将参数转换为 application use case

不负责：

- 业务规则
- 文件传输细节
- TUI 状态管理

### TUI 层

负责：

- 页面状态
- 键盘事件
- 列表筛选
- 预览视图
- 进度展示
- 用户确认

不负责：

- record 查找规则
- tag JSON 读写规则
- SSH/SFTP 细节
- 车端命令拼装

### 业务层

负责：

- tag 数据模型
- tag 文件读写
- record 定位
- export 任务编排
- clip 生命周期
- recorder/channel/module 等用例

不直接处理 TUI 事件，也不直接打印终端样式。

### 基础设施层

负责：

- 本地命令执行
- 远程命令执行
- SSH 连接
- SFTP 传输
- 文件系统访问
- 超时和取消

## 核心接口

```go
type Runner interface {
    Run(ctx context.Context, req CommandRequest) (CommandResult, error)
    Stream(ctx context.Context, req CommandRequest) (<-chan OutputChunk, <-chan error)
}

type Transport interface {
    MkdirAll(ctx context.Context, path string) error
    CopyFile(ctx context.Context, src string, dst string, opts CopyOptions) error
    CopyDir(ctx context.Context, src string, dst string, opts CopyOptions) error
}

type TagStore interface {
    Append(ctx context.Context, tag Tag) error
    List(ctx context.Context, date string) ([]Tag, error)
    ListAll(ctx context.Context) ([]DatedTags, error)
}

type RecordLocator interface {
    Locate(ctx context.Context, tagTime time.Time, root string) (RecordSelection, error)
}
```

## tag 数据契约

tag 文件继续使用 JSON，文件路径保持：

```text
/mdrive_data/bag/tag_YYYYMMDD.json
```

结构保持可读性：

```json
[
  {
    "time": "2026-06-06 21:52:55",
    "time_compact": "20260606215255",
    "message": "用户输入的信息",
    "record_root": "/mdrive_data/bag"
  }
]
```

导出目录：

```text
/media/tag_export/tag_YYYYMMDD_HHMMSS/
  tag_info.json
  record.xxx.mcap
```

导出的 `tag_info.json` 在原始 tag 上补充：

- `record_status`
- `current_record`
- `record_paths`
- `export_record_paths`
- `clip_enabled`
- `clip_paths`

这样可以明确区分原始 record 和实际导出的文件。

## record 定位规则

record 定位只在导出阶段执行，不在 `tag info` 阶段执行。

规则：

1. 根据 tag 时间选择同日期 `record_YYYYMMDD_HHMMSS` 目录。
2. 只允许选择开始时间小于等于 tag 时间的目录。
3. 选择满足条件的最新目录。
4. 只在该目录内查找 `record.*.HHMMSS.mcap`，不跨目录。
5. 当前包必须满足 `record_time <= tag_time`。
6. 当前包不能比 tag 时间早超过 60 秒。
7. 导出当前包、前两个包、后一个包。
8. 缺少前包或后包时允许 partial，但必须在 `record_status` 中体现。

这些规则必须覆盖单元测试。

## clip 规则

`tag exp --clip` 的 clip 处理流程：

1. 先定位原始 record。
2. 为每个导出任务创建唯一 clip 工作目录或唯一输出名前缀。
3. 调用：

```text
mkit edit -k /sensor/lidar/scan camera2 camera3 camera5 camera6 camera7 camera81 camera82 camera83 camera84 -f <input.mcap> -o <output_dir>
```

4. 解析 mkit 输出，但不能只依赖“目录最新文件”。
5. 记录原始路径和 clip 后路径映射。
6. 成功导出后删除临时 clip 文件。
7. 失败或用户取消时通过 defer 清理。

## 配置策略

默认值写在 `internal/config/defaults.go`：

- `SOC2_IP=192.168.10.3`
- `MOUNT_ROOT=/media/data`
- `BAG_ROOT=/mdrive_data/bag`
- `TAG_EXPORT_ROOT=/media/tag_export`
- `MDRIVE_EXPORT_ROOT=/media/mdrive_export`
- `MAX_RECORD_LAG_SECONDS=60`

环境变量可覆盖默认值：

- `MDRIVE_TAG_BAG_ROOT`
- `MDRIVE_TAG_NOW`
- 其他车端固有环境变量仍从环境读取

命令行参数优先级最高。

## 错误处理和日志

所有业务错误用结构化错误包装：

- `ErrNotFound`
- `ErrInvalidInput`
- `ErrCommandFailed`
- `ErrTransferFailed`
- `ErrPartialRecord`
- `ErrCanceled`

CLI 输出简洁错误。

TUI 显示：

- 错误摘要
- 失败命令
- exit code
- stdout/stderr 尾部
- 建议下一步

## 测试策略

第一阶段必须建立测试基础：

- `tag.Store` 使用临时目录测试 JSON 读写。
- `RecordLocator` 用表驱动测试覆盖边界。
- `ClipService` 使用 fake runner 测试命令构造和清理。
- `Transfer` 使用 fake transport 测试导出任务编排。
- CLI 参数解析测试确保兼容现有调用。

不要求第一阶段对真实 SSH/SFTP 做自动化集成测试，但接口必须可替换 fake。

## 迁移兼容策略

重构期间保留 `md.sh`：

- 先新增 Go 二进制 `go-md`。
- `md.sh` 的 `tag` 子命令可先代理到 Go 实现。
- 其他子命令继续走 Bash。
- Go 覆盖一个模块后，再切换对应 Bash 子命令。
- 全部迁移完成后，再考虑让 `/usr/local/bin/md` 指向 Go 二进制。

