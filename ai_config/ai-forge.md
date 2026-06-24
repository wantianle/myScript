# ai\-forge

# AI Forge 用户指南

FO: @聂晓楠



欢迎使用 AI Forge！本指南将帮助你快速了解和上手 AI Forge。

---

## 💻 如何安装？

### Linux/macOS 系统

```Bash
curl -fsSL https://go-self-update.oss-cn-shenzhen.aliyuncs.com/ai-forge/latest/install.sh | bash
```

### Windows 系统\(powershell\)

```ABAP
iex (iwr -UseBasicParsing https://go-self-update.oss-cn-shenzhen.aliyuncs.com/ai-forge/latest/install.ps1)
```



## 快速开始

#### 获取内网secret

登陆 [intranet\.minieye\.tech](https://intranet.minieye.tech/profile) 然后按下图获取 `your-key-secret`,注意不要从PDCL平台获取该密钥,两个平台的密钥不能混用

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=Y2Y4YjkyZTE4NjUxYTZlYmFjN2U2YjZlNjE1ZWM2ZmFfN2EwOTM0ODZkYzIyY2Y5ODg0NDhkZWUxY2VlMzc3ZGNfSUQ6NzYxNzY5MzkyODA1NzUwNjc4MF8xNzgyMjkzMjQ2OjE3ODIzNzk2NDZfVjM)



```Bash
# 登录 https://intranet.minieye.tech/profile
# your-key-id 是工号
# your-key-secret 按照下图获取
# 初次登陆会将your-key-id和your-key-secret写入环境变量,后续登陆时可以使用简化命令
# 使用 Claude Code
ai-forge login -i your-key-id -s your-key-secret
# 简化命令
ai-forge login

# 使用codex

ai-forge login -i your-key-id -s your-key-secret -p codex
# 简化命令
ai-forge login -p codex
```





## 反馈需求



