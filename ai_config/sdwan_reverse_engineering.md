# SDWAN 二进制逆向全记录

> 从零开始，用抓包 + 符号表 + 反汇编，还原一个无源码二进制文件的完整通信协议。

---

## 目录

1. [背景：我们要干什么](#1-背景我们要干什么)
2. [工具清单：用到了哪些命令](#2-工具清单用到了哪些命令)
3. [第一步：认识目标文件](#3-第一步认识目标文件)
4. [第二步：抓包看通信](#4-第二步抓包看通信)
5. [第三步：符号表——函数名就是文档](#5-第三步符号表函数名就是文档)
6. [第四步：反汇编——确认每个字节的含义](#6-第四步反汇编确认每个字节的含义)
7. [协议完整规格](#7-协议完整规格)
8. [原理总结](#8-原理总结)
9. [Go 重写实战：从零到跑通的完整调试记录](#9-go-重写实战从零到跑通的完整调试记录)
   - [9.1 TLV 长度语义](#91-调试第一轮tlv-长度语义理解错误)
   - [9.2 IP 字节序反转](#92-调试第二轮ip-字节序反转)
   - [9.3 心跳格式 + 序列号](#93-调试第三轮echoreq-字段偏移--序列号)
   - [9.4 DATA 类型错误](#94-调试第四轮data-包类型错误)
   - [9.5 seq 递增被拒](#95-调试第五轮seq-递增被拒绝)
   - [9.6 收包漏 0x14](#96-调试第六轮收包方向漏掉-0x14)
   - [9.7 最终结果](#97-最终的-ping)
   - [9.8 教训总结](#98-调试教训总结)

---

## 1. 背景：我们要干什么

公司 IT 提供了一个叫 `sdwand` 的二进制文件，它的功能是：

- 连上公司 SDWAN 服务器，建立加密隧道
- 创建虚拟网卡 `iwan1`，分配内网 IP
- 添加路由 `192.168.0.0/16 dev iwan1`，让所有内网流量走隧道

**问题：没有源码。** 我们想把它移植到 Windows，或者用 Go/Rust 重写，必须先把协议逆向出来。

---

## 2. 工具清单：用到了哪些命令

| 命令 | 作用 | 类比 |
|------|------|------|
| `file` | 看文件基本属性 | 右键 → 属性 |
| `strings` | 提取文件中所有可打印字符串 | 在一本书里高亮所有英文单词 |
| `stat` | 文件时间戳 | 文件修改日期 |
| `tcpdump` | 抓网络包 | 在网线上装窃听器 |
| `nm` | 列出二进制中的函数名和变量名 | 翻书的目录 |
| `objdump -d` | 反汇编：把机器码翻译成汇编指令 | 把摩斯密码译成英文 |
| `readelf` | 读 ELF 文件元数据 | 查身份证信息 |
| `hexdump` / `tcpdump -X` | 十六进制查看器 | 用显微镜看数据 |

---

## 3. 第一步：认识目标文件

### 3.1 它是什么格式？

```bash
file sdwand
# ELF 64-bit LSB executable, x86-64, dynamically linked,
# for GNU/Linux 2.6.32, with debug_info, not stripped
```

关键信息逐字解释：

| 字段 | 含义 |
|------|------|
| `ELF 64-bit` | Linux 原生可执行文件 |
| `x86-64` | 64 位 Intel/AMD CPU |
| `dynamically linked` | 依赖系统的 `.so` 库文件（不是静态编译） |
| `GNU/Linux 2.6.32` | 最低内核版本要求 |
| `with debug_info` | **调试信息没删！** 函数名、变量名都在 |
| `not stripped` | **符号表没剥！** 这是逆向的黄金状态 |

**原理：** 编译器在生成二进制时，可以保留"调试信息"——包括原始函数名、变量名、甚至源代码行号。发布给用户时通常会 `strip` 掉（节省空间 + 增加逆向难度），但运维没做这一步。

### 3.2 什么时候编的？

```bash
strings sdwand | grep GCC
# GCC: (GNU) 4.8.5 20150623 (Red Hat 4.8.5-44)
```

GCC 4.8.5 是 **CentOS 7 / RHEL 7** 的默认编译器（2015 年发布）。运维的编译机大概率还跑着 CentOS 7。

`stat sdwand` 显示文件修改时间是 2026-04-02，这是二进制被复制到本机的时间，不是编译时间。

**原理：** GCC 编译器会在二进制里嵌入一个 `.comment` 段，记录编译工具链版本。`readelf -p .comment` 可以读出。

### 3.3 字符串里藏着什么？

```bash
strings sdwand | grep -E 'tun|auth|config|error'
```

输出：
```
/etc/sdwan/iwan.conf        ← 配置文件路径
/tmp/iwan.log               ← 日志路径
/dev/net/tun                ← TUN 设备路径
/proc/net/route             ← 读取系统路由表
AUTH start                  ← 状态机字符串
AUTH timeout
sdwan peer AUTH REJECTED
sdwan DATA ESTABLISHED      ← 隧道建立成功
```

**原理：** C 程序里所有字符串常量（`printf("AUTH start")` 中的 `"AUTH start"`）在编译后原样保留在二进制中。`strings` 扫描整个文件，把连续的 ASCII 可打印字符提取出来。这就像在一本外文书里找英文单词——虽然看不懂整句话，但单词透露出大量信息。

---

## 4. 第二步：抓包看通信

### 4.1 抓包命令

```bash
# 停止现有服务，避免干扰
sudo systemctl stop sdwan

# 后台抓包，只抓 port 10010
sudo tcpdump -i any port 10010 -w /tmp/sdwan_handshake.pcap -s 0 &

# 手动启动 sdwand 触发握手
sudo /usr/local/bin/sdwand &
sleep 10

# 检查握手是否成功
ip addr show iwan1

# 停止抓包
sudo pkill tcpdump
```

**原理：** `tcpdump` 利用 Linux 内核的 `libpcap` 机制，把经过网卡的数据包原封不动地复制一份存到 `.pcap` 文件。`-s 0` 表示抓完整包（不截断），`-w` 写入文件而非打印到屏幕。

### 4.2 看包摘要

```bash
tcpdump -r sdwan_handshake.pcap -n | head -30
```

```
17:56:39.335751 IP 192.168.16.40.38296 > 183.238.28.18.10010: UDP, length 53
17:56:39.352232 IP 183.238.28.18.10010 > 192.168.16.40.38296: UDP, length 50
17:56:39.354857 IP 192.168.16.40.38296 > 183.238.28.18.10010: UDP, length 56
17:56:41.357195 IP 192.168.16.40.38296 > 183.238.28.18.10010: UDP, length 60
17:56:41.394899 IP 183.238.28.18.10010 > 192.168.16.40.38296: UDP, length 60
...
```

**发现：是 UDP 不是 TCP！** 之前看配置文件只知道 `port=10010`，抓包才确认传输层协议。

前 3 个包长度不同（53, 50, 56）→ 握手阶段。之后全是 60 字节成对出现 → 心跳。

### 4.3 看十六进制内容

```bash
tcpdump -r sdwan_handshake.pcap -X -c 5
```

这是最关键的一步。输出是这样的（包 1，客户端→服务器）：

```
0x0000:  4500 0051 fc99 4000 4011 9931 c0a8 1028   E..Q..@.@..1...(
0x0010:  b7ee 1c12 9598 271a 003d a51f 1300 0000   ......'..=......
0x0020:  0000 0000 39c6 b588 3923 9270 1064 efe9   ....9...9#.p.d..
0x0030:  e0dd 4e98 0304 059c 0107 7761 6e74 6c02   ..N.......wantl.
0x0040:  121e e5ce 5d5b a10d 72dc 0423 c3f5 5b69   ....][..r..#..[i
0x0050:  d6                                       .
```

**原理：** `-X` 参数要求 tcpdump 同时打印 hex 和 ASCII。左列是十六进制，右列是 ASCII 可打印字符（点表示不可打印）。

> **怎么读 hex？**
> - UDP 头部占 8 字节，在 IP 头部之后
> - IP 头部是 20 字节。所以 UDP 数据从第 28 字节开始（IP 头 20 + UDP 头 8）
> - 这个例子里数据从 `0x001c` 开始：`13 00 00 00 00 00 00 00 39 c6 b5 88...`

**一眼看出来的信息：**

| 字节位置 | Hex | 解读 |
|---------|-----|------|
| 第一个字节 | `13` | 不是随机数——所有包 1 都是 `13`，是**消息类型** |
| `0x3b-0x3f` | `7761 6e74 6c` | ASCII 解码 = `wantl`，用户名**明文传输**！ |
| 7 个包之后 | `0304059c` | 反复出现在不同包中，是**协议版本号或魔数** |
| 包 3 里 | `fe80::` | IPv6 链路本地地址——**TUN 接口用 IPv6** |

**读 hex 的核心技巧：找规律。** 如果某个字节每次位置相同但值不同，可能是序列号；如果每次都一样，可能是版本号；如果拼出来是人读的字符串，那就是字符串。

---

## 5. 第三步：符号表——函数名就是文档

### 5.1 nm 命令

```bash
nm sdwand | grep ' T \| t ' | sort
```

输出分类：

**T（Text，全局函数）** 和 **t（Text，局部函数）**。

> **原理：** ELF 文件的符号表（`.symtab` 段）记录了所有函数和全局变量的名字及地址。`nm` 读这个表。`T` 表示代码段中的全局符号，`t` 表示局部符号。

### 5.2 函数名分类解读

**协议消息处理：**
```
sdwan_sendOPEN          ← 发送 OPEN 请求（包 1）
sdwan_onOPENACK         ← 处理服务器 OPENACK 应答（包 2）
sdwan_onOPENREJ         ← 处理服务器拒绝
sdwan_sendECHOREQ       ← 发送心跳请求（包 4+）
sdwan_onECHORESP        ← 处理心跳应答
sdwan_onDATA            ← 处理隧道数据
sdwan_onCLOSE           ← 处理断开连接
```

**数据包构造：**
```
sdwan_pktopen           ← 构造 OPEN 包
sdwan_pktechoreq        ← 构造心跳包
sdwan_pktDNS            ← 构造 DNS 查询包
sdwan_parse_answer      ← 解析服务器应答
sdwan_parseDNS          ← 解析 DNS 应答
```

**认证和加密：**
```
sdwan_pktsign           ← 计算包签名（MD5）
sdwan_pktverify         ← 验证包签名
sdwan_set_key           ← 设置加密密钥
sdwan_encrypt           ← 加密数据
sys_md5init             ← MD5 初始化
sys_md5update           ← MD5 更新
sys_md5final            ← MD5 完成
AES_set_encrypt_key     ← 设置 AES 加密密钥
AES_encrypt             ← AES 加密
```

**TUN 设备操作：**
```
tun_init                ← 初始化 TUN 设备
tun_deinit              ← 销毁 TUN 设备
tun_set_ip              ← 设置 TUN 接口 IP
tun_set_mtu             ← 设置 MTU
tun_send                ← 向 TUN 口写数据
tun_recv                ← 从 TUN 口读数据
```

**网络和配置：**
```
sock_udpinit            ← 初始化 UDP socket
sock_sendto             ← 发送 UDP 数据
sock_recvfrom           ← 接收 UDP 数据
cfg_load                ← 加载配置文件
cfg_valid               ← 校验配置
route_handle             ← 管理路由表
sdwclnt_load_defroute   ← 读取系统默认路由
sdwclnt_set_iproute     ← 添加静态路由
```

### 5.3 数据结构线索

`nm` 还能找到全局变量：
```
sdwan_echopkt_t         ← 心跳包结构体
echorespcnt             ← 心跳应答计数器
```

这些名字就是程序员的注释——看到 `sdwan_pktechoreq` 就知道它构造心跳包，不需要猜。

---

## 6. 第四步：反汇编——确认每个字节的含义

函数名告诉你"做什么"，反汇编告诉你"怎么做"。

### 6.1 objdump -d 命令

```bash
objdump -d sdwand --start-address=0x404054 --stop-address=0x4040d8
```

**原理：** CPU 只能执行机器码（一串十六进制数字）。`objdump -d` 把机器码翻译成人类可读的汇编指令（mov、call、add 等）。虽然没源码那么直观，但配合函数名可以精确推断逻辑。

### 6.2 反汇编 sdwan_pktsign——签名算法

```asm
40406d: call   4013ad <sys_md5init>       ; 1. 初始化 MD5
404088: call   4013fb <sys_md5update>     ; 2. MD5_Update(header, 8)
40408d: movb   $0x6d,-0x20(%rbp)          ; 3. 'm' = 0x6d
404091: movb   $0x77,-0x1f(%rbp)          ; 4. 'w' = 0x77
4040a8: call   4013fb <sys_md5update>     ; 5. MD5_Update("mw", 2)
4040ca: call   4015b9 <sys_md5final>      ; 6. MD5_Final(hash)
```

翻译成人话：

```c
MD5_Init();
MD5_Update(header, 8);      // 取包头前 8 字节
MD5_Update("mw", 2);        // 加固定盐值 "mw"
MD5_Final(signature);       // 输出 16 字节签名
```

**原理：** `movb $0x6d` 是把十六进制 `0x6d` 写入内存。查 ASCII 表：`0x6d` = `'m'`，`0x77` = `'w'`。拼在一起就是字符串 `"mw"`——这是签名算法的盐值。知道这个，我们重写时就能算出完全一致的签名。

### 6.3 反汇编 sdwan_pktopen——OPEN 包结构

```asm
404765: movb   $0x13,(%rax)               ; byte[0] = 0x13 (消息类型 OPEN)
40477e: movw   $0x0,0x2(%rax)             ; byte[2-3] = 0
404788: movl   $0x0,0x4(%rax)             ; byte[4-7] = 0
404796: call   404054 <sdwan_pktsign>     ; 计算 16 字节签名到 byte[8-23]

; ---- TLV 字段 1: 协议版本 ----
4047a3: movb   $0x3,(%rax)                ; type = 3
4047aa: movb   $0x4,0x1(%rax)             ; length = 4
; ... 后面 2 字节是高/低位的 MTU 值 ...

; ---- TLV 字段 2: 用户名 (明文) ----
404800: movb   $0x1,(%rax)                ; type = 1
; ... strlen(username) + 2 作为长度 ...
; ... memcpy 用户名原文 ...

; ---- TLV 字段 3: 密码 (AES 加密) ----
404850: movb   $0x6d,-0x1c0(%rbp)         ; 盐值 'm'
404857: movb   $0x77,-0x1bf(%rbp)         ; 盐值 'w'
; ... memcpy username 到盐值后面 ...
4048a0: call   4013fb <sys_md5update>     ; MD5("mw" + "wantl")
4048b6: call   4015b9 <sys_md5final>      ; 输出 16 字节 → 作为 AES 密钥
4048d1: call   405b39 <AES_set_encrypt_key>; 用 MD5 结果初始化 AES
4048da: movb   $0x2,(%rax)                ; type = 2
4048e5: movb   $0x12,0x1(%rax)            ; length = 18 (0x12)
40490c: call   40675e <AES_encrypt>        ; AES 加密密码 16 字节
```

翻译成 C 代码：

```c
// 包头
pkt[0] = 0x13;              // OPEN
pkt[1] = config.encrypt;   // 0
pkt[2..3] = 0;
pkt[4..7] = 0;
pktsign(pkt);              // MD5(header[0..7] + "mw") → pkt[8..23]

// TLV 1: 协议/MTU
pkt[24] = 3;               // type
pkt[25] = 4;               // length
pkt[26] = config.mtu >> 8; // MTU 高字节 (0x05)
pkt[27] = config.mtu;      // MTU 低字节 (0x9c, 总计 0x059c = 1436)

// TLV 2: 用户名
pkt[28] = 1;                     // type
pkt[29] = strlen(user) + 2;     // length
memcpy(&pkt[30], user, len);     // "wantl"

// TLV 3: 加密密码
md5_init();
md5_update_concat("mw", user);  // salt + username
md5_final(aes_key);             // 128-bit key
AES_set_encrypt_key(aes_key);
pkt[...] = 2;                   // type
pkt[...] = 0x12;                // length = 18
AES_encrypt(password_block);    // 加密
```

### 6.4 反汇编 sdwan_pktechoreq——心跳包结构

```asm
404a36: movb   $0x15,(%rax)               ; byte[0] = 0x15 (ECHO REQ)
404a3d: movb   $0x0,0x1(%rax)             ; byte[1] = 0
404a4d: mov    %dx,0x2(%rax)              ; byte[2-3] = session_id
404a5c: mov    %edx,0x4(%rax)             ; byte[4-7] = seq
404a66: call   404054 <sdwan_pktsign>     ; byte[8-23] = MD5 签名

; ---- 24 字节后是心跳特有数据 ----
404a7c: ... os_curusec()                  ; byte[24-31] = 时间戳(微秒)
404a8e: ... config.pipeid                 ; byte[32-35]
404a9c: ... config.pipeidx                ; byte[36-39]
404aaa: ... echorespcnt                   ; byte[40-43]
404abd: movb   $0x54,(%rax)               ; 'T'
404ac4: movb   $0x44,0x1(%rax)            ; 'D'
404acc: movb   $0x52,0x2(%rax)            ; 'R'
404ad0: movb   $0x54,(%rax)               ; 覆盖! → 'T' → 最终 "TDRi"
; ... htonl(session_id) 在 +4 ...
; ... 0 在 +8 ...
; 总长 0x3c = 60
```

这里有个细节：`T` 被写了两次——先写 `T`，然后同一个位置再写 `T`（覆盖，结果还是 `T`）。最终四个字节是 `T D R i`——心跳魔术字。

---

## 7. 协议完整规格

### 7.1 通用包头（24 字节）

```
Offset  Size  Field
------  ----  -----
  0      1    消息类型:
                0x12 = OPENACK (服务器应答)
                0x13 = OPEN    (客户端请求)
                0x14 = TUN 协商
                0x15 = ECHOREQ (心跳请求)
                0x16 = ECHORESP(心跳应答)
                0x18 = DATA    (隧道数据)
  1      1    加密标志 (iwan.conf: encrypt=0/1)
  2      2    会话 ID (OPENACK 后分配，OPEN 时为 0)
  4      4    序列号
  8     16    MD5(header[0..7] + "mw")   ← 固定盐值 "mw"
```

### 7.2 OPEN 消息（类型 0x13）

包头(24) + TLV：

```
TLV 1: type=3, len=4, value=MTU(1436)        → hex: 03 04 05 9c
TLV 2: type=1, len=strlen(user)+2, value=用户名  → hex: 01 07 77616e746c
TLV 3: type=2, len=0x12, value=AES加密密码      → hex: 02 12 [18 bytes AES]
TLV 4: (条件) type=8, len=3, value=加密标志      → 仅 encrypt!=0 时出现
```

### 7.3 密码加密流程

```
1. aes_key = MD5("mw" + username)     // 16 字节
2. 用 aes_key 做 AES-128 加密密码 (16 字节)
3. 在密码数据前加 2 字节标记 (0x02 0x12 = type=2 len=18)
```

注意：密钥由 `用户名 + 固定盐值 "mw"` 决定，不是随机生成的。这意味着：
- 同一个用户名的密钥永远相同
- 密码变化时加密结果才会变
- 服务器侧用同样的公式算出密钥来解密

### 7.4 心跳包（类型 0x15/0x16，60 字节）

```
Offset  Size  Field
------  ----  -----
  0     1    0x15 (请求) / 0x16 (应答)
  1     1    0x00
  2     2    会话 ID
  4     4    序列号
  8    16    MD5 签名
 24     8    时间戳 (微秒精度)
 32     4    pipeid
 36     4    pipeidx
 40     4    echorespcnt (应答计数)
 44     4    魔术字 "TDRi"
 48     4    htonl(session_id)
 52     8    保留 (0)
```

心跳频率：每 2 秒一对。

### 7.5 DATA 消息（类型 0x18）

包头(8) + 载荷。`encrypt=0` 时载荷即 TUN 设备收发的原始 IP 包。`encrypt=1` 时用 AES 加密。

### 7.6 状态机

```
                 ┌─→ sdwan_onOPENREJ ─→ "AUTH REJECTED" ─→ 退出
                 │
sdwan_sendOPEN ──┼─→ sdwan_onOPENACK ─→ "DATA ESTABLISHED"
  (0x13)         │        (0x12)              │
                 │                            ├─→ tun_init()
                 └─→ 超时 ─→ "AUTH timeout"   ├─→ sdwclnt_set_iproute()
                                              │
                    每 2 秒 ←─────────────────┤
                    sdwan_sendECHOREQ (0x15)   │
                         ↓                    │
                    sdwan_onECHORESP (0x16) ──┘
                                              │
                    隧道数据 ←────────────────┤
                    sdwan_onDATA (0x18) ──────┘
                                              │
                    sdwan_onCLOSE ─→ 重连 ────┘
```

---

## 8. 原理总结

### 8.1 逆向方法论

整个过程遵循一个清晰的路径：

```
1. file + strings  →  搞清楚"这是什么"
2. tcpdump         →  抓真实通信数据
3. nm              →  读函数名（程序员的注释）
4. objdump -d      →  看汇编确认每个字节含义
5. 交叉验证         →  pcap hex ↔ 反汇编 ↔ 函数名 三方对照
```

每一步都有抓手：抓包给你"真实数据长了什么样"，符号表给你"程序员怎么称呼这些东西"，反汇编给你"底层逻辑是什么"。三者互相印证，就不会猜错。

### 8.2 为什么能这么顺利？

这个二进制有三个"助攻"：

1. **没 strip** — 函数名全在，相当于带注释的加密文档
2. **有 debug_info** — 编译时用了 `-g`，数据结构成员偏移都能反推
3. **encrypt=0** — 隧道没加密，抓包看到的是明文协议字段

如果运维 strip 了、开了加密、或者用的是自定义混淆协议，逆向难度会高一个数量级。

### 8.3 下一步

协议完整规格已经有了，重写只需要：

- **Go/Rust**：约 500 行，一个 UDP socket + TUN 设备 + MD5 + AES
- **交叉编译**：Go 一把出 Windows `.exe` 和 Linux 二进制
- **改进点**：可以加多服务器自动切换、断线重连、GUI、流量统计等

> **更新**：Go 版已实现并跑通。详见第 9 章。

---

## 9. Go 重写实战：从零到跑通的全调试记录

这一章不是教你怎么写代码——而是还原真实的调试过程：假设你按逆向出来的协议规格写完了代码，编译通过，一跑，什么现象？然后怎么定位？怎么修？

### 9.0 代码结构

```
sdwan-go/
├── main.go         ← 入口, 信号处理, 路由管理
├── config.go       ← iwan.conf 解析
├── protocol.go     ← 包头, MD5签名, AES密码, TLV编解码
├── tunnel.go       ← TUN 设备创建/配置/销毁
├── client.go       ← UDP socket, 握手, 心跳, 数据转发
└── go.mod
```

初版约 400 行，编译产物 2.7MB (stripped)。

---

### 9.1 调试第一轮：TLV 长度语义理解错误

**现象**：

```
[AUTH] OPENACK received, session=7
[FATAL] OPENACK missing IP info: local="" gateway=""
```

认证通过了！但 IP 解析为空。

**排查方法**：加了一行 `log.Printf("[DEBUG] OPENACK raw: %x", openAck)` 打印原始 hex。

OPENACK 的字节布局：
```
03 04 05 9c    ← Type=3(MTU), Len=4, Total=4字节
04 06 0a 64 64 1f ← Type=4(本机IP), Len=6, Total=6字节
06 06 0a 0a 0a 01 ← Type=6(DNS), Len=6, Total=6字节
05 0a 77 1d 1d 1d ... ← Type=5(网关IP), Len=10, Total=10字节
```

**根因**：代码把 TLV 的 `length` 字段当成"仅 value 的长度"，但实际上 `length` 是**整条 TLV 的总长**（含 type 和 length 自己各 1 字节）。代码流程是：

```go
pos += 2                // 跳过 type + length
// ... 读 value
pos += length           // 应该从 TLV 开头跳过 length 字节
```

但在 pos 已经 +2 之后又 += length，游标跳偏了，吃掉了下一条 TLV 的开头。

**正确的逻辑**：`pos += length`（从 TLV 起始位置计算）。

**修复**：删除 `pos += 2`，直接从 TLV 起始索引计算 value 位置 `valueStart := pos + 2`。

---

### 9.2 调试第二轮：IP 字节序反转

**现象**：用户指出 `119.29.29.29` 被解析成 `29.29.29.119`。

**排查**：原版 C 代码用了一个很 trick 的 IP 拼法：

```c
// ptr+5<<24 | ptr+4<<16 | ptr+3<<8 | ptr+2
// pcap 数据：77 1d 1d 1d
// 结果：0x1d << 24 | 0x1d << 16 | 0x1d << 8 | 0x77 = 0x1d1d1d77
```

这个 uint32 值 `0x1d1d1d77` 存在 x86 小端内存里变成 `[77, 1d, 1d, 1d]`，然后丢给 `inet_ntop`（按大端读），输出 `119.29.29.29`。两次字节序翻转互相抵消。

**根因**：我在 Go 里照搬了同样的移位，但用 `ip >> 24` 直接格式化时，Go 的算术移位不论内存布局，得到了错误的结果。

**修复**：跳过字节序体操，直接按 wire bytes 顺序读：
```go
r.LocalIP = fmt.Sprintf("%d.%d.%d.%d", data[0], data[1], data[2], data[3])
```

---

### 9.3 调试第三轮：ECHOREQ 字段偏移 + 序列号

**现象**：
```
[TUN] iwan1 IP=10.100.100.48/24
[STATUS] SDWAN tunnel is running
// 然后……完全静默。ping 100% packet loss。没有任何数据回来。
```

**排查步骤 1——加心跳日志**：在 `heartbeatLoop` 和 `Run()` 里加了 `[HB SEND]` 和 `[RECV]` 日志，发现服务器完全没回 ECHORESP。

**怀疑 1**：ECHOREQ 格式不对。对比反汇编确认 TDRi 位置：
```asm
404ab1: add $0x18, %rax    ; pktsign返回 + 0x18(24) = 总偏移 24+24 = 48
```
TDRi 应该在字节 48，我们的代码放在字节 44——差了 4 字节。fix：中间插入 4 字节 padding。

**怀疑 2**：seq 从 0 开始。看了 OPENACK 响应：
```
12 00 00 5c e2 96 e5 7f ...
           ^^^^^^^^^^^ seq = 0xe296e57f
```
原版 OPENACK 处理代码：
```asm
404eab: mov 0x4(%rax), %edx   ; 从 OPENACK header 取 seq
404eb2: mov %edx, 0x20(%rax)  ; 存到 struct+0x20，后续发包都从这里取
```
seq 应该从 OPENACK 的 seq 字段继承，不是从 0 开始。fix：`c.seq = ParseOPENACKSeq(data)`。

**修复后结果**：心跳通了，`[HB] ECHORESP received` 出现！但 ping 还是不通。

---

### 9.4 调试第四轮：DATA 包类型错误

**现象**：心跳通了，TUN 也在读数据并发包，但服务器不回应任何 DATA。

**怀疑**：DATA 包的 type 字节不对。看 `sdwclnt_tun_recv` 反汇编：
```asm
; encrypt == 0 分支
40582e: movb $0x14, (%rax)    ← 写的是 0x14！
; encrypt != 0 分支  
4057fa: movb $0x18, (%rax)    ← 0x18 只在加密模式用
```

**根因**：`encrypt=0` 时 DATA 包类型是 `0x14`，不是 `0x18`！我把 `MsgTUNSetup` (0x14) 和 `MsgDATA` (0x18) 搞混了。fix：`buildDataPacket` 里 `encrypt=0` 时用 `0x14`。

**修复后结果**：服务器开始响应了，发了一个 `type=0x17` 的 24 字节包，但数据仍然不通。

---

### 9.5 调试第五轮：seq 递增被拒绝

**现象**：DATA(0x14) 发出去了，服务器回了 `0x17`（拒绝/通知），数据仍然不通。

**排查**：抓原版二进制（`sdwand`）的数据包对比。用 `tcpdump` 抓原版发 ping 时的包：

```
原版 ECHOREQ: 15 00 00 11 96 12 d8 1a ...   seq = 0x9612d81a
原版 DATA:    14 00 00 11 96 12 d8 1a ...   seq = 0x9612d81a  ← 完全一样！
服务器回包:   14 00 00 11 96 12 d8 1a ...   seq = 0x9612d81a  ← 服务器原样回
```

**根因**：seq 在整个会话中是**固定不变的**——它是从 OPENACK 里拿到的会话标识，不是包序号。而我们每次发包都 `c.seq++`，seq 不断变化，服务器看到 seq 对不上直接丢弃。

反汇编确认：原版的 TUN 发送逻辑（`sdwclnt_tun_recv`）中，递增的是 `struct+0x114` 和 `struct+0x118` 这两个单独的计数器，而 seq（`struct+0x20`）从来没有被修改过。

**修复**：删除所有 `c.seq++`，全程使用 OPENACK 返回的固定 seq。

---

### 9.6 调试第六轮：收包方向漏掉 0x14

**现象**：seq 固定后，`[RECV]` 日志显示服务器大量发回 `type=0x14` 的 92 字节包——数据到了！但 ping 仍不通。

**排查**：看 `Run()` 里的收包处理：
```go
switch mt {
case MsgECHORESP:       // 0x16 → 处理 ✓
case MsgDATA:           // 0x18 → 处理，但实际收到的是 0x14！
// 0x14 → default → 静默丢弃 ✗
```

**根因**：服务器回包用 `0x14`，而我们只转发 `0x18`（`MsgDATA`）。`0x14` 在 switch 里走到 default，被丢弃了。TUN 口永远收不到 ICMP 响应。

**修复**：
```go
case MsgTUNSetup, MsgDATA:  // 0x14 + 0x18 都转发
    c.tun.Write(data[8:])
```

---

### 9.7 最终的 ping

```
ping -c 3 hfs.minieye.tech
64 bytes from 192.168.2.126: icmp_seq=1 ttl=61 time=20.3 ms
64 bytes from 192.168.2.126: icmp_seq=2 ttl=61 time=13.8 ms
64 bytes from 192.168.2.126: icmp_seq=3 ttl=61 time=15.4 ms

3 packets transmitted, 3 received, 0% packet loss
```

---

### 9.8 调试教训总结

| 错误类型 | 例子 | 教训 |
|---------|------|------|
| **协议字段语义误读** | TLV length 是整个 TLV 总长 | 反汇编看 `ptr += length` 才能确认语义 |
| **字节序陷阱** | x86 LE + inet_ntop BE 双重翻转 | 直接按 wire bytes 读，跳过语言/平台差异 |
| **硬编码偏移** | TDRi 位置 44 vs 48 | 反汇编的 `add $0x18` 就是正确答案 |
| **状态继承遗忘** | seq 应从 OPENACK 继承 | 完整的反汇编覆盖所有状态转移 |
| **类型映射错误** | 0x14 vs 0x18 的 encrypt 分支 | 读 if-else 汇编时注意 `.je` 跳转目标 |
| **双向不对称** | 发 0x14 收也 0x14，但只处理 0x18 | 别忘了收包方向也有对称的类型 |
| **时序问题** | DATA 抢在心跳前 | 状态机有时序依赖，抄原版的初始化顺序 |

---

*文档生成于 2025-06-24，逆向目标：`sdwand` (Build ID: 10bfbf4e40dd5c2b26d2e76828ebb73d46e20211)*
*Go 重写完成于 2025-06-24，源码目录：`~/dev/myScript/sdwan-go/`*
