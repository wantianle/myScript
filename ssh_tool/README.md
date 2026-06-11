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

安装脚本会自动安装命令入口、zsh/bash 补全，并创建默认配置文件 `~/.sshc_config`。安装后如果当前 shell 还没有识别 `sshc` 或补全，重新加载 shell 配置：

```bash
source ~/.zshrc
# 或
source ~/.bashrc
```

## 功能和命令

### `sshc <vehicle>`

默认连接流程：

1. 登录正式环境 `https://xiaozhu.minieye.cc` 和测试环境 `https://xz-test.minieye.cc`。测试环境页面入口是 `https://xz-test.minieye.cc/navigation`。
2. 在两个环境查询车辆，车名匹配忽略大小写。
3. 检查 `c4Online == true`，不在线则退出。
4. 查询两个环境的车端 `22/tcp` 端口映射。
5. 默认优先正式环境；只有正式环境没有 22 映射，并且测试环境已有 `status=active`、`frpc_connected=true` 的 22 映射时，才复用测试环境。
6. 在选中的环境里，无映射时创建 `{ "device_port": 22, "protocol": "tcp", "device_id": "..." }`。
7. 映射为 `inactive`、`fail` 或 `failed` 时先删除再重建。
8. 等待映射初始化 5 秒，然后检查状态并探测公网 TCP 端口。
9. 最多等待 10 秒；只有 `status=active`、`frpc_connected=true` 且公网端口可连接才继续。
10. 执行 `ssh-copy-id` 上传配置私钥对应的 `.pub` 公钥，按提示输入车端密码。
11. 执行 `ssh nvidia@<server_ip> -p <server_port>`。

### `sshc <vehicle> -v`

只查看信息，不创建映射，不执行 SSH。输出内容包括：

- 车辆 ID。
- `c4Online` 状态。
- 车辆版本信息，例如 `c4`、`mdrive`、`mdrive_conf`。
- 已有端口映射、状态和可复制的 SSH 命令。

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
- 无在线候选时会提示 `sshc: no online vehicle candidates for ...`。

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
