# sdwan

Go 实现的 SDWAN VPN 隧道客户端（公司 `sdwand` 替换品）。

支持 Linux / macOS (Intel + Apple Silicon) / Windows 三个平台。

## 目录结构

```
sdwan-go/
├── main.go
├── client.go           ← UDP, 握手, 数据转发
├── config.go           ← iwan.conf 解析, 服务器列表
├── protocol.go         ← 包头, MD5签名, AES加密, TLV
├── tunnel_linux.go     ← Linux: /dev/net/tun + ip命令
├── tunnel_darwin.go    ← macOS: utun + ifconfig
├── tunnel_windows.go   ← Windows: Wintun + netsh
├── tray/               ← Windows 托盘管理工具
│   ├── main.go / menu.go / manager.go
│   ├── config.go / latency.go / icon.go
│   └── go.mod / go.sum
├── Makefile
├── go.mod / go.sum
├── README.md
└── dist/               ← 编译产物
    ├── sdwan-linux-amd64
    ├── sdwan-macos-amd64
    ├── sdwan-macos-arm64
    ├── sdwan-windows-amd64.exe
    ├── sdwan-tray.exe
    └── wintun.dll
```

## 编译

```bash
make              # 全平台编译
make linux        # 只编 Linux
make macos        # 只编 macOS
make windows      # 只编 Windows
make VERSION=2.0  # 指定版本号
```

## 配置文件 (iwan.conf)

INI 格式，`#` 开头为注释。**配置文件必须放在 exe 同目录**（默认读取当前目录的 `iwan.conf`），跨平台统一。

```ini
server=minieye.9966.org    # 可不填，启动时会交互选择
username=your_username
password=your_password
port=10010
mtu=1436
encrypt=0
pipeid=0
pipeidx=0
tunname=iwan1              # TUN 网卡名称（可选，默认 iwan1）
routenet=192.168.0.0/16    # 内网路由网段（可选，默认 192.168.0.0/16）
```

`server` 为空时启动会弹出交互选单。可选服务器：

| 序号 | 地址 |
|------|------|
| 1 | minieye.9966.org |
| 2 | dwan.minieye.tech |
| 3 | minieye.8866.org |
| 4 | minieye.2288.org |
| 5 | youjia.8866.org |

## 命令行用法

```bash
./sdwan -list                    # 列出可选服务器
./sdwan -server 3                # 指定第 3 个服务器
./sdwan -f /path/to/iwan.conf   # 指定配置文件
./sdwan -version                 # 查看版本信息
```

## Linux 部署

### 快速测试

```bash
sudo ./dist/sdwan-linux-amd64 -f /etc/sdwan/iwan.conf
```

### systemd 服务（开机自启 + 后台运行）

```bash
# 1. 拷贝二进制
sudo cp dist/sdwan-linux-amd64 /usr/local/bin/sdwan

# 2. 创建服务文件
sudo tee /etc/systemd/system/sdwan.service > /dev/null << 'EOF'
[Unit]
Description=SDWAN VPN Tunnel
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/sdwan -f /etc/sdwan/iwan.conf -server 1
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# 3. 启用并启动
sudo systemctl daemon-reload
sudo systemctl enable --now sdwan

# 4. 查看状态
sudo systemctl status sdwan
journalctl -u sdwan -f
```

如果 `iwan.conf` 没填 `server`，`-server 1` 跳过交互选单，直接连第一个。

## macOS 部署

macOS 内核自带 utun 虚拟网卡，无需安装驱动。

### Intel Mac

```bash
chmod +x dist/sdwan-macos-amd64
sudo ./dist/sdwan-macos-amd64 -f /path/to/iwan.conf
```

### Apple Silicon Mac (M1/M2/M3)

```bash
chmod +x dist/sdwan-macos-arm64
sudo ./dist/sdwan-macos-arm64 -f /path/to/iwan.conf
```

### 开机自启（LaunchDaemon）

```bash
# 1. 拷贝二进制
sudo cp dist/sdwan-macos-arm64 /usr/local/bin/sdwan

# 2. 创建 plist
sudo tee /Library/LaunchDaemons/com.minieye.sdwan.plist > /dev/null << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.minieye.sdwan</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/sdwan</string>
        <string>-f</string>
        <string>/etc/sdwan/iwan.conf</string>
        <string>-server</string>
        <string>1</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/var/log/sdwan.log</string>
    <key>StandardErrorPath</key>
    <string>/var/log/sdwan.log</string>
</dict>
</plist>
EOF

# 3. 加载并启动
sudo launchctl load /Library/LaunchDaemons/com.minieye.sdwan.plist
sudo launchctl start com.minieye.sdwan

# 4. 查看状态
tail -f /var/log/sdwan.log
```

## Windows 部署

### 文件准备

将以下文件放在同一目录（推荐 `C:\ProgramData\sdwan\`）：

| 文件 | 说明 |
|------|------|
| `sdwan-tray.exe` | 系统托盘管理工具（推荐日常使用） |
| `sdwan-windows-amd64.exe` | SDWAN 核心客户端 |
| `wintun.dll` | Wintun 虚拟网卡驱动 |
| `iwan.conf` | 配置文件 |

```powershell
mkdir C:\ProgramData\sdwan -Force
copy dist\sdwan-tray.exe C:\ProgramData\sdwan\
copy dist\sdwan-windows-amd64.exe C:\ProgramData\sdwan\
copy wintun.dll C:\ProgramData\sdwan\
copy iwan.conf C:\ProgramData\sdwan\
```

### 托盘工具（推荐）

`sdwan-tray.exe` 是一个静默托盘小工具，功能类似 Clash for Windows 的精简版：

| 功能 | 说明 |
|------|------|
| 连接开关 | 右键菜单一键启用/断开 VPN |
| 服务器切换 | 查看各线路延迟，一键切换 |
| 编辑配置 | 自动打开记事本编辑 `iwan.conf`，保存后自动重载 |
| 查看日志 | 一键打开 `sdwan-tray.log` |
| 开机自启 | 配合任务计划程序，后台静默运行 |

启动方式：
1. 双击 `sdwan-tray.exe`（无窗口，系统托盘出现图标）
2. 右键托盘图标 → 选择"启用 VPN"
3. 如需切换服务器：右键 → 服务器线路 → 选择目标服务器

### 托盘工具开机自启

```powershell
# 管理员 PowerShell
schtasks /create /tn "SDWAN Tray" `
  /tr "C:\ProgramData\sdwan\sdwan-tray.exe" `
  /sc onstart /ru SYSTEM /rl highest /f
```

### 核心客户端（命令行）

```powershell
cd C:\ProgramData\sdwan
.\sdwan-windows-amd64.exe
```

> 运行后可在 **设备管理器 → 网络适配器** 中看到 `iwan1`（Wintun 适配器）。

### 日志

程序启动后自动在同目录生成 `sdwan.log`（命令行）或 `sdwan-tray.log`（托盘工具）：

```powershell
# 实时查看日志
Get-Content C:\ProgramData\sdwan\sdwan-tray.log -Wait -Tail 20
```

### 多平台兼容性说明

| 平台 | TUN 驱动 | 配置文件默认路径 |
|------|---------|----------------|
| Linux | `/dev/net/tun`（内核自带） | `./iwan.conf` |
| macOS | `utun`（内核自带） | `./iwan.conf` |
| Windows | `wintun.dll`（需放 exe 同目录） | `./iwan.conf` |

所有平台均使用当前目录的 `iwan.conf` 作为默认配置，可用 `-f` 指定其他路径。

## 验证隧道

```bash
# 成功连接后应能 ping 通内网
ping 10.10.10.1
ping hfs.minieye.tech    # 应解析到 192.168.x.x
```

## 停止隧道

```bash
# 前台运行时直接 Ctrl+C
# systemd 服务：
sudo systemctl stop sdwan
```
