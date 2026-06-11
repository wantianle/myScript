# md Go TUI 重构计划

## 原则

- 每一阶段都要产出可运行版本。
- 优先迁移高复杂、高风险、可测试收益明显的模块。
- 不一次性重写所有 Bash 功能。
- TUI 和业务逻辑同步推进，但业务逻辑必须能通过 CLI 单独验证。
- Go 版功能稳定后，再让 Bash 入口代理到 Go。

## 阶段 0：基线和骨架

目标：建立 Go 项目骨架、构建链路和基础约束。

任务：

- 创建 `md_tool/go-md`。
- 初始化 `go.mod`。
- Go 基线版本使用 `1.26`。
- 引入基础依赖：
  - `github.com/spf13/cobra`
  - `github.com/charmbracelet/bubbletea`
  - `github.com/charmbracelet/bubbles`
  - `github.com/charmbracelet/lipgloss`
  - `golang.org/x/crypto/ssh`
  - `github.com/pkg/sftp`
- 建立目录结构：
  - `cmd/md`
  - `internal/config`
  - `internal/runner`
  - `internal/cli`
  - `internal/tui`
- 实现 `md --version`、`md help`。
- 增加 Makefile 或构建脚本。
- 增加 Linux amd64、Linux arm64 的交叉编译目标。

验收：

- `go test ./...` 通过。
- `go build ./cmd/md` 通过。
- 能在当前机器运行 `./md --version`。
- `make cross` 产出 `dist/md_linux_amd64` 和 `dist/md_linux_arm64`。

## 阶段 1：tag 核心逻辑

目标：把 tag 的 JSON、列表、record 定位从 Bash/Python 迁移到 Go。

任务：

- 实现 `internal/tag/model.go`：
  - `Tag`
  - `TagFile`
  - `RecordSelection`
  - `ExportInfo`
- 实现 `TagStore`：
  - `Append`
  - `List(date)`
  - `ListAll`
  - pretty JSON 写入
- 实现 `RecordLocator`：
  - 同日期 record 目录选择
  - 单目录内 mcap 查找
  - 60 秒限制
  - 前二后一选择
  - partial/found/stale/not_found 状态
- 实现 CLI：
  - `md tag info <message>`
  - `md tag list`
  - `md tag exp -d <date> -i <ids...> --dry-run`
  - `tag info/list/exp` 软链接模式
- 暂时不做真实导出，`exp --dry-run` 输出将导出的 tag 和 record。

测试：

- tag message 包含空格、特殊符号、中文。
- tag 文件按日期写入。
- tag list 按日期分组并重置序号。
- record locator 覆盖：
  - 正常 found
  - 缺前包 partial
  - 缺后包 partial
  - 当前包超过 60 秒 stale
  - 只有未来包 not_found
  - 不能跨 record 目录
  - 同一天多个 record 目录选择最新可用目录

验收：

- Go 版 `tag info/list` 与当前 Bash 行为一致。
- `exp --dry-run` 能解释为什么找到或找不到 record。

## 阶段 2：导出和 SFTP 传输

目标：用 Go 替代 `rsync` 的 tag 导出路径。

任务：

- 实现 `internal/sshx`：
  - SSH client 配置
  - mini 优先探测
  - mini 不通时交互输入用户名
  - 密钥认证
  - 连接超时
- 实现 `internal/transfer`：
  - SFTP mkdir
  - 单文件 copy
  - 目录 copy
  - 进度回调
  - 文件存在策略
- 实现 `md tag exp` 真正导出：
  - `/media/tag_export/tag_YYYYMMDD_HHMMSS`
  - `tag_info.json`
  - record 文件
- 增加 `--local-root` 测试模式，用本地目录模拟 PC 端。
- 导出前处理同名目录策略：
  - 默认复用目录但覆盖同名文件
  - 后续可加 `--clean` 或 `--unique`

测试：

- fake transport 验证导出任务顺序。
- 本地 copy 模式验证实际文件落盘。
- 无 record 时仍导出 `tag_info.json`，并标记 `record_status`。

验收：

- 不依赖 `rsync` 完成 tag 导出。
- 导出结果目录和 JSON 字段符合架构文档。

## 阶段 3：clip 支持

目标：把 `tag exp --clip` 迁移到 Go，并修复 Bash 版遗留风险。

任务：

- 实现 `ClipService`。
- 所有 `mkit edit` 调用走 `runner.Run`。
- 每次导出生成唯一 clip 输出目录或唯一文件名前缀。
- 捕获取消信号并清理临时文件。
- `tag_info.json` 同时记录：
  - 原始 `record_paths`
  - 实际导出的 `export_record_paths`
  - `clip_paths`
  - `clip_enabled`
- 支持批量 tag 去重 clip。

测试：

- fake runner 验证命令参数包含 `-k`、`-f`、`-o`。
- mkit 失败时导出中止并清理。
- mkit 输出文件名异常时仍能按唯一目录识别本次产物。
- 用户取消时触发清理。

验收：

- `md tag exp --clip -d ...` 不依赖 Bash 逻辑。
- 不会误选旧 clip 文件。
- 不会因同名 record 覆盖其他 tag 的 clip 文件。

## 阶段 4：统一 TUI 第一版

目标：建立 `md` 默认 TUI，并接入 tag/export。

任务：

- 实现 TUI app shell：
  - 首页
  - 状态栏
  - 帮助栏
  - 错误弹层
  - 任务进度视图
- 实现 tag 页面：
  - 日期列表
  - tag 列表
  - tag 详情预览
  - 多选导出
  - clip 开关
- 使用：
  - `bubbles/list` 做列表和筛选
  - `bubbles/viewport` 做详情和日志输出
  - `bubbles/progress` 做传输进度
- 保持 CLI 子命令可用。

测试：

- model update 单元测试覆盖主要按键。
- 业务服务用 fake 注入，TUI 不连真实车端。

验收：

- 运行 `md` 进入 TUI。
- 可从 TUI 选择某日期 tag 并导出。
- 不依赖 `fzf`、`less`、`rsync`。

## 阶段 5：md e/export 迁移

目标：替代当前 `md e` 的文件/目录交互导出。

任务：

- 实现文件扫描服务：
  - 扫描 `$MDRIVE_DATA_ROOT/{bag,log,core,pcap,crash_log,perf}`
  - 文件大小、时间、类型展示
  - 隐藏文件过滤
- TUI 文件选择：
  - fuzzy 筛选
  - 多选
  - 预览路径和大小
  - 传输进度
- 使用 SFTP 传输。
- CLI 保留：
  - `md export`
  - `md e`
  - 可选非交互参数后续再补。

测试：

- fake filesystem 测试扫描。
- fake transport 测试多选导出。

验收：

- Go 版 `md e` 不再依赖 `fzf` 和 `rsync`。

## 阶段 6：record/channel/service 迁移

目标：迁移低交互但高频使用的车端服务命令。

任务：

- `md record on/off`
  - 只控制 soc2 `Recorder`
  - `on` 前检查 soc2 数据盘挂载和空间
  - `off` 不阻塞于硬盘检查
- `md c/channel`
  - 使用 `dtop`
  - 检查本地和 soc2 命令可用性
  - TUI 中可作为独立命令输出视图
- `md start/stop/restart/status`
  - soc1/soc2 mdrive service 控制
  - 命令超时和错误展示

测试：

- fake runner 验证命令构造。
- mount 不存在时 record on 失败。
- record off 不检查硬盘。

验收：

- Go 版覆盖当前 Bash 的 record/channel/service 主路径。

## 阶段 7：module/log/check 迁移

目标：迁移复杂交互和诊断页面。

任务：

- `md module`
  - TUI 列表展示 soc1/soc2 supervisor 状态
  - 快捷键 start/stop/restart
  - 日志预览 viewport
- `md log`
  - journalctl 流式输出
  - viewport 替代 less
- `md check`
  - 网络检查
  - 时间检查
  - 硬盘检查
  - 设备检查并发执行
  - TUI 汇总面板

测试：

- runner fake 覆盖状态解析。
- 并发检查可取消。

验收：

- 高频查看和诊断链路可在 TUI 内完成。

## 阶段 8：vmc/install/upgrade/rollback 迁移

目标：迁移包管理流程。

任务：

- remote config 读写。
- version 搜索和选择。
- upgrade/install/rollback 流程编排。
- 升级前检查和确认。
- 失败中止策略和结果汇总。

测试：

- fake `vmc` 输出解析。
- 多版本选择输入校验。
- 安装失败后不误报成功。

验收：

- Go 版包管理行为清晰可诊断。

## 阶段 9：切换入口和清理 Bash

目标：让 Go 二进制成为主入口。

任务：

- 修改部署脚本，安装 Go 二进制为 `/usr/local/bin/md`。
- 创建 `/usr/local/bin/tag` 软链接。
- Bash `md.sh` 保留为 legacy fallback 或逐步删除。
- 移除 `md_tool/bin` 中不再需要的 `fzf`、`less`、`rsync` 依赖包。
- 更新 `AGENTS.md`、README 和使用说明。

验收：

- 新环境部署后默认使用 Go 版 `md`。
- 常用命令在车端验证通过。
- legacy Bash 入口有明确退役说明。

## 风险和缓解

### TUI 跨平台差异

风险：不同终端对按键、颜色、窗口大小支持不同。

缓解：

- 所有功能保留 CLI 命令路径。
- TUI 页面做最小可用布局，不依赖复杂鼠标操作。

### SFTP 替代 rsync 的性能差异

风险：大 mcap 文件传输缺少 rsync 的断点和增量能力。

缓解：

- 第一版实现进度和失败重试。
- 文件已存在且大小一致时跳过。
- 后续再评估断点续传或 rsync 算法。

### 车端外部命令不稳定

风险：`mkit`、`vmc`、`dtop` 输出变化。

缓解：

- 输出解析集中在对应 service。
- 失败时保留原始 stdout/stderr 尾部。
- 对关键解析加样例测试。

### Bash 和 Go 并行期行为不一致

风险：用户混用两个入口导致结果不同。

缓解：

- 先让 Bash 代理已迁移的 Go 子命令。
- 每次迁移只切一个功能域。
- 文档记录当前由 Bash 还是 Go 承载。

## 推荐近期执行顺序

1. 完成阶段 0。
2. 完成阶段 1 的 tag store 和 record locator。
3. 用 dry-run 对比 Bash 当前 `tag exp` 的 record 选择结果。
4. 完成阶段 2 的本地 copy 测试模式。
5. 再接入真实 SFTP。
6. 完成阶段 3 的 clip。
7. Bash `tag` 子命令代理到 Go。
