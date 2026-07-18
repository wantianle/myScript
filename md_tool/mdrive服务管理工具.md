# mdrive 服务管理工具

`md`（mdrive 管理工具）是一套面向车辆工程师的命令行运维工具集，用于管理双 SoC（soc1/soc2）架构下的 mdrive 服务、模块、日志、版本和录包等操作。工具集包含三个脚本：`ssh.sh`（免密配置）、`deploy.sh`（批量部署）、`md.sh`（车端管理主脚本）。

---

## 目录

- [快速入门](#快速入门)
- [命令参考](#命令参考)
  - [init —— 首次初始化](#init--首次初始化)
  - [check —— 车辆状态自检](#check--车辆状态自检)
  - [stop / start / restart / status —— 服务管理](#stop--start--restart--status--服务管理)
  - [log —— 服务日志](#log--服务日志)
  - [m (module) —— 交互式模块管理](#m-module--交互式模块管理)
  - [c (channel) —— DDS 消息查看](#c-channel--dds-消息查看)
  - [record —— 录包控制](#record--录包控制)
  - [tag —— 打点标注与导出](#tag--打点标注与导出)
  - [umount —— 安全弹出硬盘](#umount--安全弹出硬盘)
  - [install —— 手动安装版本](#install--手动安装版本)
  - [upgrade —— 自动升级](#upgrade--自动升级)
  - [rollback (rb) —— 回滚版本](#rollback-rb--回滚版本)
  - [e (export) —— 交互式文件导出](#e-export--交互式文件导出)
  - [remote —— 远程分支管理](#remote--远程分支管理)
- [部署指南](#部署指南)
  - [部署前置：连接车辆网络](#部署前置连接车辆网络)
  - [ssh.sh —— SSH 免密配置](#sshsh--ssh-免密配置)
  - [deploy.sh —— 工具批量部署](#deploysh--工具批量部署)
- [环境变量](#环境变量)
- [使用注意事项](#使用注意事项)

---

## 快速入门

从零开始，5 步完成工具部署并使用：

### 第 1 步：连接车辆局域网

将笔记本电脑连接到车辆的局域网（WiFi 或网线直连）。车辆局域网通常为 `192.168.10.x` 网段，soc1 固定 IP 为 `192.168.10.2`，soc2 固定 IP 为 `192.168.10.3`。

### 第 2 步：配置 SSH 免密登录

在笔记本电脑上执行 `ssh.sh`，配置到车辆 soc1 和 soc2 的免密登录：

```bash
bash md_tool/ssh.sh
```

选择局域网模式 `[1]`，脚本会自动探测并缓存车辆密码（先试 `mini!@#123.com`，再试 `nvidia`，都不匹配则交互式输入），生成 ed25519 密钥对并分发公钥。

> **每台车每台电脑只需执行一次。** 之后可以通过 `ssh soc1` / `ssh soc2` 免密快捷登录。

### 第 3 步：批量部署 md 工具

```bash
bash md_tool/deploy.sh
```

选择部署模式（局域网 `[1]` 或公网 `[2]`），再选择部署内容（仅软件包 / 仅 md.sh / 全部部署），脚本自动完成上传、安装、初始化。

> 首次部署时需要车辆的 sudo 密码（用于安装 sudoers 免密规则），后续部署不再需要。

### 第 4 步：登录车端

```bash
ssh soc1
```

### 第 5 步：开始使用

```bash
md check          # 检查车辆状态
md status         # 查看服务状态
md m              # 交互式管理模块
md upgrade        # 自动升级版本
```

---

## 命令参考

所有命令均在 soc1 上执行（部署工具只安装在 soc1，通过内部 SSH 管理 soc2）。

> **约定**：`<>` 必选参数，`[]` 可选参数，`()` 可简写命令。

```
Usage:
  md <c(command)> [a(arguments)]

Commands:
  init                                            每次部署工具需要初始化免密并安装工具到系统
  check                                           检查车辆状态
  umount                                          安全弹出硬盘
  upgrade                                         自检并升级最新包版本
  install [version]                               手动升级多个组件版本，也可通过参数升级单个组件版本
  rb(rollback) [version_keyword]                  根据 remote 文件或指定关键字回滚升级任意版本的包
  stop/start/restart/status [1(soc1)|2(soc2)]     同时管理 soc1&2 服务，也可以通过参数指定单端
  log <1(soc1)|2(soc)>                            查看 5 分钟内 soc1/soc2 服务日志
  c(channel) [1(soc1)|2(soc2)]                    查看 soc1/soc2 DDS 消息
  m(module)                                       管理 soc1&2 模块，查看对应模块日志和开发日志
  record [on]|<off>                               开启关闭 soc2 的 Recorder
  tag info [message]                              记录打点信息；不带 message 时先锁定时间再输入描述
  tag list                                        按日期列出已记录的打点信息
  tag exp [--clip] -d <date> [-i <ids|ranges...>]  导出 tag 关联 mcap 到本地电脑，支持 -i 1 3 5 或 1-20
  e(export)                                       交互式选择导出 MDRIVE_DATA_ROOT 下的文件或目录
  remote <add|del|list>                           管理本地包对应的远程分支
                                                   remote add <name> [branch|'-'] [platform]
                                                   remote del <name>
```

---

### init —— 首次初始化

```bash
md init
```

部署工具到车辆后的初始化命令，由 `deploy.sh` 自动调用，通常不需要手动执行。初始化内容包括：

1. 配置 soc1 → soc2 的 SSH 免密（生成 ed25519 密钥对，分发公钥）
2. 安装受限 sudo NOPASSWD 权限到 `/etc/sudoers.d/mdrive_perms`（soc1 和 soc2 双端），白名单包括：
   - `systemctl start/stop/restart mdrive.service`
   - `journalctl -eu mdrive.service`
   - `supervisorctl status/start/stop/restart`
   - `umount -l /media/data`、`mount`、`e2fsck -yf`
   - `dpkg -i /tmp/md-tool/*.deb`
3. 复制 `md` 脚本到 `/usr/local/bin/md`
4. 创建 `tag` 命令软链接到 `/usr/local/bin/tag`
5. 安装 bash 自动补全脚本到 `/etc/bash_completion.d/md`
6. 配置 `~/.ssh/config` 添加 soc2 快捷登录别名

---

### check —— 车辆状态自检

```bash
md check
```

执行全车状态自检，包含以下检查项：

| 检查项 | 内容 |
|--------|------|
| **网络** | soc2 连通性、ad.minieye.tech 连通性 |
| **设备** | 10 个内置设备 Ping 检测（LiDAR×3、Airy×3、GNSS/INS、MCU、OBU、RearScreen） |
| **时间** | soc1/soc2 与服务器时间对比，误差超过 20 秒报警 |
| **磁盘** | 根分区使用率、内盘缓存使用率（不足 5GB 警告）、外盘挂载诊断 |
| **服务** | soc1/soc2 mdrive 服务运行状态 |

**自动修复**：check 发现硬盘挂载异常时会提示是否自动修复，支持以下修复类型：

| 错误码 | 说明 | 修复方式 |
|--------|------|----------|
| 1 | 硬盘未识别 | 检查硬件连接 |
| 2/3 | 未挂载 / 挂载残留 | 卸载后重新挂载 |
| 4/5 | 挂载点不可访问 / I/O 错误 | `e2fsck -yf` 修复文件系统 |
| 6 | 软链接指向错误 | 修正 `$MDRIVE_DATA_ROOT` 软链接 |
| 7 | 内盘空间不足 | 清理 `.cache` 目录 |

> **注意**：不同车型设备检测数量不同，部分设备离线属于正常现象，不影响使用。

---

### stop / start / restart / status —— 服务管理

```bash
md stop                # 停止 soc1 + soc2 的 mdrive 服务
md start               # 启动 soc1 + soc2 的 mdrive 服务
md restart             # 重启 soc1 + soc2 的 mdrive 服务
md status              # 查看 soc1 + soc2 的服务状态
```

**指定单端参数**：

```bash
md stop 1              # 仅停止 soc1
md start soc2           # 仅启动 soc2
md restart soc1         # 仅重启 soc1
md status 2             # 仅查看 soc2
```

参数支持简写 `1` / `2` 或全称 `soc1` / `soc2`。

> **注意**：这里的 stop/start/restart 控制的是 systemd 层面的 `mdrive.service` 服务，不是 supervisor 管理的具体模块。模块启停请使用 `md m`。

---

### log —— 服务日志

```bash
md log          # 查看 soc1 最近 5 分钟的 mdrive 服务日志（过滤 ptp4l/phc2sys 噪声）
md log 2        # 查看 soc2 最近 5 分钟的日志
```

使用 `journalctl -eu mdrive.service --since "5 min ago" -f`，实时跟随输出。按 `Ctrl-C` 退出。

---

### m (module) —— 交互式模块管理

```bash
md m
```

打开 fzf 交互式界面，展示 soc1 + soc2 所有 supervisor 管理模块的状态。这是日常调试最常用的命令。

**界面说明**：

| 颜色 | 状态 |
|------|------|
| 🟢 绿色 | RUNNING（正常运行） |
| 🟡 黄色 | RUNNING（刚启动，uptime 为 0） |
| 🔴 红色 | FATAL / STOPPED / BACKOFF 等异常 |

**快捷键**：

| 快捷键 | 功能 |
|--------|------|
| **Tab** | 多选模块（选中后高亮） |
| **↑ / ↓** | 上下导航 |
| **Enter** | 查看选中模块的 supervisor 日志（SV 日志，`less -R +F` 实时跟随） |
| **Alt-Enter** | 查看选中模块的 GLOG 开发日志（自动匹配 `$GLOG_log_dir` 下的软链接） |
| **Alt-S** | 启动选中的所有模块（支持批量） |
| **Alt-X** | 停止选中的所有模块（支持批量） |
| **Alt-R** | 重启选中的所有模块（支持批量） |
| **Ctrl-R** | 刷新模块列表（重新拉取 supervisorctl status） |
| **Esc** | 退出 |

**日志匹配逻辑**：GLOG 日志通过配置文件 `stdout_logfile` 和 `/mdrive/bin` 命令行参数智能匹配，候选名按优先级为：二进制名 → 去掉 `mdrive_` 前缀名 → 小写模块名 → 小写模块去掉前缀名。未命中时自动弹出 fzf 选择器列出所有 `*.INFO*` 软链接。

---

### c (channel) —— DDS 消息查看

```bash
md c            # 查看 soc1 的 DDS channel 消息
md c 2          # 查看 soc2 的 DDS channel 消息
```

调用 `dtop` 工具实时显示 DDS 通信通道的消息流量。soc2 模式会通过 SSH 自动设置 `MDRIVE_ROOT_DIR`、`GLOG_log_dir` 等环境变量后执行。

---

### record —— 录包控制

```bash
md record on    # 开启 soc2 Recorder 录包
md record off   # 停止 soc2 Recorder 录包
```

**开启前检查**：
1. 检查 soc2 数据盘是否挂载到 `/media/data`
2. 检查剩余空间是否 ≥ 200GB（不足时警告）
3. 硬盘未挂载时拒绝启动 Recorder

> 录包操作在 soc2 上执行，通过 supervisorctl 控制 Recorder 模块。

---

### tag —— 打点标注与导出

`tag` 是一组打点标注子工具，用于在录包过程中记录关键时间点和描述信息，后续可基于打点导出对应的 mcap 文件。

#### tag info —— 记录打点

```bash
tag info "变道失败"                # 带描述直接打点
tag info                          # 不带参数：锁定当前时间，交互式输入描述
```

打点信息保存为 JSON 文件：`$MDRIVE_TAG_BAG_ROOT/tag_YYYYmmdd.json`。

#### tag list —— 列出打点

```bash
tag list
```

按日期分组列出所有打点记录，显示序号、时间和描述信息：

```
20250713
  1. 2025-07-13 10:23:15  变道失败
  2. 2025-07-13 11:05:42  接驳点定位偏移
```

#### tag exp —— 导出打点录包

```bash
tag exp -d 20250713                              # 导出当天全部打点对应的 mcap
tag exp -d 20250713 -i 1 3 5                     # 导出指定序号的 mcap
tag exp -d 20250713 -i 1-20                      # 导出序号范围的 mcap
tag exp --clip -d 20250713 -i 1 3                # 导出裁剪后的 mcap（去除激光雷达原始点云）
```

导出逻辑：
1. 根据打点时间匹配 60 秒内的最近 mcap 文件，定位前后共 4 个 mcap 包
2. `--clip` 模式使用 `mkit edit -k /sensor/lidar/scan` 裁剪掉激光雷达原始点云数据，减小文件体积
3. 通过 SSH 反向隧道回传到本地电脑的 `/media/tag_export/`

> **需要反向隧道**：`tag exp` 需要建立 SSH 反向隧道才能回传文件（同 `export` 命令）。

---

### umount —— 安全弹出硬盘

```bash
md umount
```

停止双端 mdrive 服务后安全卸载 `/media/data` 数据盘，反复尝试最多 5 次。适用于车辆下电前安全移除硬盘。

---

### install —— 手动安装版本

```bash
md install                          # 打开 vi 编辑器，粘贴版本信息后批量安装
md install 1.2.3-tongxiang-abc123  # 安装指定版本到匹配的包
```

**无参数模式**：打开 vi 编辑器，粘贴版本信息文本（如从发布系统复制的内容），脚本自动正则提取以下包的版本号并安装：

| 包名 | 匹配模式 | 说明 |
|------|----------|------|
| `mdrive` | `mdrive` | 主程序 |
| `mdrive_conf` | `mdrive_conf\|conf` | 配置文件包 |
| `mdrive_map` | `mdrive_map\|map` | 地图数据包 |
| `mdrive_dep` | `mdrive_dep\|dep` | 依赖包（平台相关） |
| `mdrive_model` | `mdrive_model\|model` | 模型文件包 |

`mdrive_map` 安装时会加 `--deps` 选项。所有包安装后会验证实际安装版本与预期版本是否一致。

**带版本参数**：通过 `vmc fsearch -v <version>` 模糊匹配并安装。

---

### upgrade —— 自动升级

```bash
md upgrade
```

工作流程：
1. 执行 `check`（自检），环境异常时提示是否强制继续
2. 扫描 `~/.md_remotes` 配置文件中的分支绑定
3. 对比远程最新版本与当前安装版本
4. 有多分支配置时交互选择目标版本
5. 确认后停止服务 → 逐个安装 → 验证 → 启动服务

> **前置条件**：必须先通过 `md remote add` 配置分支绑定。

---

### rollback (rb) —— 回滚版本

```bash
md rollback                     # 无参数：从 remote 文件选择包，fzf 交互选版本
md rollback tongxiang_abc123   # 模糊搜索匹配的版本，fzf 交互选择
md rb tongxiang                 # 简写形式
```

工作流程：
1. 无参数时从 `~/.md_remotes` 中选择要回滚的包
2. `vmc fsearch` 搜索历史版本（最多 100 条）
3. fzf 交互选版本后确认执行
4. 自动停止服务、清理内盘缓存、安装回滚版本

---

### e (export) —— 交互式文件导出

```bash
md export
md e
```

从车端的 `$MDRIVE_DATA_ROOT` 目录下交互式选择文件或目录，通过 SSH 回传到本地电脑的 `/media/mdrive_export/<时间戳>/` 目录。

当前实现会直接扫描 `$MDRIVE_DATA_ROOT` 下 **3 层以内的所有非隐藏内容**，不再限定为固定的 `bag / log / core / pcap / crash_log / perf` 目录。这样新增模块目录或新的数据类型后，无需再修改脚本。

**工作原理**：
1. 自动检测 SSH 连接类型（局域网直连 / 公网反向隧道）
2. 局域网模式：直接通过 SSH 源 IP 回传（端口 22）
3. 公网模式：检测当前会话的 SSH 反向隧道端口（`ssh -R <port>:localhost:22`），通过 `127.0.0.1:<port>` 回传
4. 配置车端到本地电脑的 SSH 免密（可能需要本地电脑的密码）
5. 在本地创建 `/media/mdrive_export` 和 `/media/tag_export` 目录

**fzf 交互**：

| 快捷键 | 功能 |
|--------|------|
| Tab | 勾选 / 取消选中 |
| Ctrl-A | 全选 / 取消全选 |
| Enter | 确认并开始传输 |

> **需要反向隧道**：公网环境下使用 `export` 和 `tag exp`，必须为当前 SSH 会话建立反向隧道：
> ```bash
> ssh -R 9999:localhost:22 ad.minieye.tech -p <车辆port>
> ```

---

### remote —— 远程分支管理

```bash
md remote list                           # 查看当前分支绑定列表
md remote add mdrive tongxiang_mdrive     # 绑定 mdrive 到 tongxiang_mdrive 分支
md remote add mdrive_conf tongxiang_conf  # 绑定配置包分支
md remote add mdrive_dep -                # '-' 表示不绑定分支，使用最新版本
md remote add mdrive_dep - orin_dsv       # 指定平台筛选
md remote del mdrive                      # 删除 mdrive 的分支绑定
```

**`-` 特殊用法**：分支名使用 `-` 表示不限制分支，`vmc fsearch` 时省略 `-v` 参数，获取该包的最新版本。

**platform 参数**：可选参数，用于筛选特定平台（如 `orin`、`orin_dsv`），`vmc fsearch` 时过滤 `platform` 字段。

配置保存在 `~/.md_remotes`，每行一条：`<包名> <分支> [平台]`。

**配置示例**：

```
mdrive tongxiang_mdrive
mdrive_conf tongxiang_conf
mdrive_dep - orin_dsv
mdrive_map K281
mdrive_model youwan1
```

---

## 部署指南

### 部署前置：连接车辆网络

部署脚本依赖 SSH 连接到车辆，需要确保笔记本与车辆网络互通：

- **局域网模式**：笔记本通过 WiFi 或网线接入车辆局域网（`192.168.10.x` 网段）
- **公网模式**：通过 `ad.minieye.tech` 的 FRP 公网映射端口访问车辆

### ssh.sh —— SSH 免密配置

> **每台车每台电脑只需配置一次**，配置后 `ssh soc1` / `ssh soc2` 即可免密登录。

```bash
bash md_tool/ssh.sh
```

#### 局域网模式 [1]

直接通过车辆局域网 IP 配置免密登录：
- soc1：`192.168.10.2:22`
- soc2：`192.168.10.3:22`

自动在 `~/.ssh/config` 中添加 `soc1` 和 `soc2` 的快捷别名。

#### 公网模式 [2]

通过 `ad.minieye.tech` 的公网 FRP 端口配置免密登录。用户输入车辆的公网映射端口（多个用空格分隔，如 `6171 6173`），脚本逐个分发公钥。

#### 密码自动探测

两种模式均支持自动密码探测与缓存：

1. 先尝试上次命中的缓存密码
2. 再按顺序尝试预设密码：`mini!@#123.com` → `nvidia`
3. 都不匹配则交互式提示用户输入
4. 命中后缓存供后续目标复用

依赖 `sshpass` 实现非交互式密码分发（如未安装则回退到交互式 `ssh-copy-id`）。

> **批量部署**：公网模式下输入多个端口，可一次性完成多台车的免密配置。

---

### deploy.sh —— 工具批量部署

> **只部署到 soc1**。soc2 由 soc1 在 `md init` 阶段通过内部 SSH 远程配置。

```bash
bash md_tool/deploy.sh
```

#### 部署模式选择

| 模式 | 说明 |
|------|------|
| 局域网 `[1]` | 直接通过 `192.168.10.2:22` 连接 soc1（默认方式） |
| 公网 `[2]` | 通过 `ad.minieye.tech:<port>` 连接 soc1，每个端口对应一台车 |

#### 部署任务选择

| 选项 | 内容 |
|------|------|
| `1` 仅部署软件包 | 上传并安装 3 个辅助 .deb 包（rsync / fzf / less） |
| `2` 仅部署 md.sh | 上传 md.sh 并执行 init（免密 + sudoers + 命令安装） |
| `3` 全部部署 | 上传软件包 + md.sh，一并安装和初始化 |

#### 部署流程

1. **免密自检**：检查目标主机 SSH 免密是否就绪，未配置的给出警告
2. **连通性检测**：通过 `nc -z` 检测目标端口可达性
3. **上传文件**：scp 上传 `bin/` 目录下的 .deb 包和 `md.sh` 到 `/tmp/md-tool/`
4. **密码探测**：自动探测车辆 sudo 密码（与 ssh.sh 逻辑一致：缓存 → 预设 → 交互式）
5. **远端执行 init**：通过 sudo -S 执行 `md.sh init`，同时注入 soc2 密码文件用于非交互式 sudoers 安装
6. **结果统计**：汇总成功 / 失败的目标列表

#### 首次部署 vs 后续部署

| | 首次部署 | 后续部署 |
|------|----------|----------|
| sudo 密码 | 需要输入（安装 sudoers） | 不需要（sudo NOPASSWD 已生效） |
| init 步骤 | 执行完整 init | `md.sh` 已在 `/usr/local/bin/md`，通常只需上传覆盖 |
| soc2 密码 | 需要（通过 deploy 注入） | soc1→soc2 SSH 免密已配置，不需要密码 |

> **批量部署**：公网模式下输入多个端口，可一次性完成多台车的工具部署。

---

## 环境变量

`md` 依赖以下环境变量，由 mdrive 环境的 `setup.sh` 自动设置。SSH 远程命令需要注意不会自动 source `.bashrc`，脚本内部已做处理。

| 变量 | 说明 | 示例值 |
|------|------|--------|
| `GLOG_log_dir` | GLOG 日志目录 | `/mnt/ufs_data/project/data/log` |
| `MDRIVE_ROOT_DIR` | mdrive 根目录 | `/mdrive` |
| `MDRIVE_DEP_DIR` | 依赖目录 | `/mdrive/mdrive_dep` |
| `MDRIVE_DATA_ROOT` | 数据目录 | `/mdrive_data`（软链接 → `/media/data/data`） |
| `MDRIVE_CACHE` | 内盘缓存目录 | `/mdrive/.cache` |
| `MDRIVE_VEHICLE_MODEL` | 车辆型号 | `ECAR_HW4` 等 |
| `MDRIVE_TAG_BAG_ROOT` | tag 打点录包根目录（可选） | `/mdrive_data/bag` |
| `MDRIVE_TAG_NOW` | tag 打点固定时间（可选） | `2025-07-13 10:00:00` |

---

## 使用注意事项

### 1. 只部署到 soc1

`deploy.sh` 只将工具部署到 soc1（车辆主 SoC）。soc2 的管理通过 soc1 上的 `md.sh` 内部 SSH（`192.168.10.3`）完成。soc2 的初始化（SSH 免密、sudoers）在 `md init` 阶段由 soc1 远程执行。

### 2. 首次部署需要 sudo 密码

每台车首次部署时需要一次 sudo 密码（安装 `/etc/sudoers.d/mdrive_perms`）。`deploy.sh` 会自动探测（先试 `mini!@#123.com`，再试 `nvidia`），都不匹配则交互式询问。后续部署不再需要（NOPASSWD 规则已生效）。

### 3. md init 做了什么

| 步骤 | 说明 |
|------|------|
| SSH 免密 | soc1 → soc2：生成 ed25519 密钥，ssh-copy-id 分发 |
| sudoers 安装 | soc1 和 soc2 双端安装 `/etc/sudoers.d/mdrive_perms` |
| 命令安装 | 复制到 `/usr/local/bin/md` + 创建 `/usr/local/bin/tag` 软链接 |
| 自动补全 | 安装 bash completion 到 `/etc/bash_completion.d/md` |
| SSH config | 添加 soc2 快捷登录别名到 `~/.ssh/config` |

**sudoers 白名单**仅限日常运维命令，不包含完全 root 权限。

### 4. 局域网 vs 公网

| | 局域网模式 | 公网模式 |
|------|-----------|----------|
| 连接方式 | 直接 `192.168.10.2/3:22` | `ad.minieye.tech:<FRP端口>` |
| 适用场景 | 在地库 / 停车场等局域网可达环境 | 车辆在远程，通过 FRP 隧道访问 |
| 速度 | 快（局域网带宽） | 受公网带宽限制 |
| 每个端口 | N/A | 每台车有独立的公网映射端口 |

### 5. ssh.sh 每车只需一次

`ssh.sh` 将笔记本电脑的公钥分发到车辆，之后所有 SSH 操作均为免密。更换电脑、重装系统或密钥丢失后需重新执行。

### 6. export 需要反向隧道

公网环境下使用 `md export` / `md e` 和 `tag exp`，车端需要将文件回传到本地电脑。由于车辆无法直接连接本地电脑，需要通过 SSH 反向隧道中转：

```bash
# 建立反向隧道（持续占用终端）
ssh -R 9999:localhost:22 ad.minieye.tech -p <车辆port>

# 另一个终端操作
ssh soc1
md export    # 自动检测 127.0.0.1:9999 隧道
```

`md export` 会自动检测当前 SSH 会话来源：如果是局域网 IP（192.168.x.x / 10.x / 172.16-31.x）则直接回传；否则扫描当前会话建立的 `ss -tlnp` 反向隧道端口。

> 多人同时操作时，脚本会检测到多个回传端口并提示手动选择，避免误传到同事的电脑。

### 7. service vs module

| 命令 | 控制层 | 对象 |
|------|--------|------|
| `md stop/start/restart` | systemd | `mdrive.service` 整体服务 |
| `md m` | supervisor | 服务内的各个模块（如 Localization、Planning 等） |

- 升级版本时脚本自动停止 systemd 服务
- 日常调试时通过 `md m` 控制单个模块更灵活

### 8. 环境变量依赖

`md.sh` 依赖多个环境变量（见上表），SSH 远程命令不会自动 source `.bashrc`，脚本通过以下方式保证变量可用：

- soc2 本地命令通过 SSH 显式传递 `-t` 分配伪终端
- channel 命令通过 `export` + `source setup.sh` 在远程显式设置
- `md init` 时使用 `HOME=/home/nvidia USER=nvidia` 覆盖环境

### 9. vmc 安装验证

`md` 在通过 `vmc install` 安装包后会**二次验证**实际安装版本与预期版本是否一致，以检测 vmc 返回码为 0 但实际安装失败的静默错误场景。

### 10. mdrive_map 安装

`mdrive_map` 安装时使用 `--deps` 参数，会自动安装依赖项。其他包使用标准安装流程。

### 11. 缓存清理

`md check` 检测到内盘缓存空间不足 5GB 时会警告（影响 OTA 版本升级）。`md install` 和 `md rollback` 在安装前会自动调用 `sys::clean` 清理缓存。缓存清理目标为 `$MDRIVE_CACHE/data` 子目录，路径经过多层安全检查后才执行删除。

### 12. 日志过滤

`md log` 默认过滤 `ptp4l` 和 `phc2sys` 日志行，减少时间同步相关的噪声输出。

### 13. 设备检测差异

`md check` 中 `INTERNAL_DEVICES` 为固定设备列表，不同车型可能配置不同数量的传感器。部分设备离线属于正常情况，**不影响整体检查结论**。

---

> **文档版本**：v1.1.0
