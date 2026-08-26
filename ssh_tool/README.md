# sshc

`sshc` 是一个小竹平台车辆 SSH 辅助工具。它按车名查询车辆状态和端口映射，必要时自动创建车端 `22/tcp` 映射，分发本机公钥，然后登录到车端。

## 安装和快速上手

安装：

```bash
./install.sh
```

配置小竹账号：

```bash
sshc config --prod-username "正式账号" --prod-password "正式密码"
sshc config --test-username "测试账号" --test-password "测试密码"
```

连接车辆：

```bash
sshc xzt500021
```

查看车辆状态、版本和端口映射，不执行 SSH：

```bash
sshc xzt500021 -v
```

为车辆创建或检查指定端口映射：

```bash
sshc xzt500021 add 8765
```

上传/下载文件：

```bash
sshc xzt500021 push ./local.txt ~/test/
sshc xzt500021 push ./a.txt ./b.txt ~/test/
sshc xzt500021 push ./conf/*.yaml ~/test/
sshc xzt500021 pull ~/test/log.txt ./
```

安装脚本会自动安装命令入口、zsh/bash 补全，并创建默认配置文件 `~/.sshc_config`。安装后如果当前 shell 还没有识别 `sshc` 或补全，重新加载 shell 配置：

```bash
source ~/.zshrc
# 或
source ~/.bashrc
```

## 功能和命令

### `sshc <vehicle>`

默认连接流程会自动完成：查询车辆状态、选择正式/测试环境、确保车端 `22/tcp` 映射可用、检查或分发本机公钥，然后执行 SSH 登录。

连接规则：

- 车名匹配忽略大小写。
- 默认优先正式环境；只有正式环境没有可用 22 映射、测试环境已有可用 22 映射时，才复用测试环境。
- 没有 22 映射时会自动创建；`inactive`、`fail` 或 `failed` 映射会删除后重建。
- 等待映射初始化 3 秒，最多等待 10 秒；只有 `status=active`、`frpc_connected=true` 且公网 TCP 端口可连接才继续。
- 车名大写后以 `T5P` 开头时使用 `root` 登录，其他车辆使用 `nvidia`。
- 先检查本机密钥是否已可登录；只有明确的公钥认证失败才会尝试密码分发公钥，网络或 SSH 错误不会误进入密码流程。

密码候选按 SSH 用户区分：T5P/root 只尝试 `MiniEye@Root1201PassWd..`，且不使用密码缓存；普通车辆/nvidia 会优先尝试缓存密码，再依次尝试 `mini!@#123.com` 和 `nvidia`。命令输出不会打印明文密码。

`sshpass` 是可选依赖；未安装时会打印中文 warning，不会报错退出，只会跳过自动密码轮询并进入交互式 fallback。安装示例：

```bash
sudo apt install sshpass
```

终端输出会自动着色：`active` / `true` 为绿色，`inactive` / `failed` 为红色，`pending` 为黄色，`[WARNING]` 为黄色；部分可复制命令和地址会使用青色。管道重定向或设置 `NO_COLOR` 环境变量时自动关闭颜色。

### `sshc <vehicle> -v` / `sshc <vehicle> --versions`

只查看信息，不创建映射，不执行 SSH。即使车辆当前离线，也会尽量展示最近一次上报的车辆信息。输出内容包括：

- 车辆名称。
- 车辆版本信息，例如 `c4`、`mdrive`、`mdrive_conf`。
- 已有端口映射（格式 `port/proto -> host:port`）、状态和 `frpc_connected` 标记。
- 22 端口映射下方显示可复制的 `ssh` 命令，用户规则同连接流程：T5P 使用 `root`，其他车辆使用 `nvidia`。
- 9000 / 8765 端口映射下方显示 `websocket` 连接地址。

### `sshc <vehicle> add <port>`

为指定车辆创建或检查端口映射，不执行 SSH。端口范围必须是 `1-65535`：

```bash
sshc xzt500021 add 8765
```

流程：

1. 登录并查询车辆，要求 `c4Online == true`。
2. 检查目标端口映射是否 `status=active`、`frpc_connected=true` 且公网端口可连接。
3. 已存在且正常 → 直接返回映射信息。
4. 映射为 `inactive`、`fail` 或 `failed` → 删除旧映射后重建。
5. 无映射 → 创建新映射并等待就绪。
6. 等待超时后仍未就绪或 TCP 不可连接则报错退出。

支持短写 `a` 替代 `add`：

```bash
sshc xzt500021 a 22
```

### `sshc <vehicle> push <local>... <remote>` / `sshc <vehicle> pull <remote>... <local>`

在本地和车辆之间传输文件。`push` 表示本地到车端，`pull` 表示车端到本地。
远端路径直接使用普通路径字符串，例如 `~/test/` 或 `/tmp/a.log`：

```bash
# 上传单个文件
sshc XZT500021 push ./local.txt ~/test/

# 上传多个本地源，最后一个参数是远端目标目录
sshc XZT500021 push ./a.txt ./b.txt ./logs ~/test/

# 本地 glob 由 shell 展开成多个源，不用加引号
sshc XZT500021 push ./conf/*.yaml ~/test/
sshc XZT500021 push ./* /mdrive/mdrive_conf/modules/MFDI

# 下载文件
sshc XZT500021 pull ~/test/log.txt ./

# 下载多个车端源；远端 glob 请加引号，避免本地 shell 提前展开
sshc XZT500021 pull '~/a.log' '~/b/*.txt' ./

# 目录默认使用 scp -r 递归传输
sshc XZT500021 push ./logs ~/test/
```

`push` 支持一个或多个本地源（最后一个参数是远端目标），因此多个源时远端目标必须是一个目录，建议以 `/` 结尾，例如 `~/test/` 或 `/mdrive/mdrive_conf/modules/MFDI/`。本地 glob 不要加引号，让 shell 展开成多个源后逐个校验。

`pull` 同样支持一个或多个车端源（最后一个参数是本地目标）。多个源下载时，本地目标必须是已存在的目录，例如 `./`；远端 glob 建议加引号，交给车端 shell 展开。

传输前会复用登录流程，查询车辆、确保车端 `22/tcp` 映射可用并完成公钥认证，
然后执行带 `-r` 的 `scp`。
远端路径不能写成 `./xxx` 或 `../xxx` 这种本地相对路径形式。`~/...` 如果被本地 shell 展开，`sshc` 会在远端参数位置尽量还原为车端 home。远端 glob 会交给 `scp` 处理；为了避免本地 shell 提前展开 glob，请用引号包住远端路径，例如：

```bash
sshc XZT500021 push ./logs/*.txt '~/test/'
sshc XZT500021 pull '~/test/*.log' ./
```

### `sshc config`

查看当前配置：

```bash
sshc config
```

更新配置：

```bash
sshc config --prod-username "正式账号" --prod-password "正式密码"
sshc config --test-username "测试账号" --test-password "测试密码"
sshc config -k "~/.ssh/id_ed25519"
```

缩略命令：

```bash
sshc cfg -u "正式账号" -p "正式密码"
```

配置说明：

- `prod_username` 和 `prod_password_md5` 保存正式环境账号。
- `test_username` 和 `test_password_md5` 保存测试环境账号。
- `-u/--username` 与 `-p/--password` 是正式环境的缩略写法。
- 密码保存 MD5，不保存明文密码；登录接口使用 `PASSWORD_MD5`。
- `keyfile` 是私钥路径，默认 `~/.ssh/id_ed25519`。
- `ssh_password_cache` 是 SSH 车端密码缓存对象，key 形如 `USER@VEHICLE_NAME`，value 是上次自动上传公钥并验证成功的明文密码。该字段用于下次优先尝试成功密码，不影响现有小竹账号配置字段。
- 如果配置的私钥不存在，会自动创建 ed25519 密钥对。
- 分发密钥时上传的是同名 `.pub` 公钥。

### 车辆名补全

安装后支持 zsh/bash 车辆名补全：

```bash
sshc 21<Tab>
```

补全规则：

- 数字输入小于 5 位会补零后匹配车辆名后缀，例如 `21` 匹配后缀 `00021`。
- 数字输入大于等于 5 位会直接匹配车辆名后缀，例如 `500010` 可以匹配 `TEST-XZT500010`。
- 不限制车辆名前缀。
- 候选只保留 `c4Online == true` 的车辆。
- 无在线候选时会提示 `[WARNING] no online vehicle candidates for ...`。
- `push` 的本地路径参数和 `pull` 的本地路径参数支持本地文件补全。

### 远端路径补全

目前不对车端路径执行 Tab 补全，只对本地路径使用 shell 文件补全。

车端路径补全需要先登录小竹平台、查询已有 SSH 端口映射，并使用本机公钥登录车辆。为避免按 Tab 时创建端口映射、分发公钥、尝试密码或长时间阻塞终端，`sshc` 不会在补全阶段执行这些操作。

远端路径请直接输入，例如 `~/test/` 或 `/tmp/a.log`。远端路径中的 `~` 和 glob 模式由最终的 `scp` 命令处理；包含 glob 的路径请使用引号，避免被本地 shell 提前展开。

Bash 多候选时通常先显示列表或补公共部分。想用 Tab 在候选间切换，可以在 `~/.inputrc` 增加：

```text
"\t": menu-complete
set show-all-if-ambiguous on
```

## 卸载和路径

卸载：

```bash
./uninstall.sh
```

卸载脚本会移除命令入口、工具目录、补全文件，并删除安装脚本写入的 shell 启动配置块。用户配置文件 `~/.sshc_config` 会保留。

安装路径：

- 命令入口：`~/.local/bin/sshc`
- 工具目录：`~/.local/share/sshc`
- 配置文件：`~/.sshc_config`
- zsh 补全：`~/.local/share/zsh/site-functions/_sshc`
- bash 补全：`~/.local/share/bash-completion/completions/sshc`

安装脚本会在 `~/.zshrc` 或 `~/.bashrc` 写入托管配置块，用于加载 `~/.local/bin` 和补全文件。账号密码不会写入 shell 配置文件。
