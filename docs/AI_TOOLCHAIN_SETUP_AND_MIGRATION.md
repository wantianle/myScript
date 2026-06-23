# AI 工具链梳理与迁移说明

这份文档讲两件事：

1. 这台机器上 `Claude Code / Codex / OpenCode / cc-switch / ai-forge` 现在到底是怎么工作的  
2. 如果你想把这一整套环境从 `mini@192.168.16.40` 直接 `rsync` 回本地，需要拷哪些文件，放到哪里

本文尽量按“小白能看懂”的方式写，不假设你已经理解：

- 什么是 provider
- 什么是协议兼容
- 什么是统一网关
- 什么是模型 ID

---

## 1. 先说结论

这台机器上现在有 3 个真正会发请求的 AI CLI 工具：

- `claude`
- `codex`
- `opencode`

另外还有 2 个“辅助工具”：

- `cc-switch`
- `ai-forge`

它们的关系可以简单理解成：

- `claude / codex / opencode`：真正拿来聊天、改代码、跑任务的工具
- `cc-switch`：本地配置管理器，负责切换 provider、写配置
- `ai-forge`：公司内网登录和订阅组切换工具

最重要的一点：

**`cc-switch` 和 `ai-forge` 本身不直接回答问题，它们只是帮其他工具拿配置和选路由。**

---

## 2. 整体脑图：把整件事拆成 4 层

理解这套环境，最容易混的就是“同一个公司出口”这件事。

建议你把整个调用过程拆成 4 层：

### 第 1 层：工具层

你实际在终端里敲的是哪个工具：

- `claude`
- `codex`
- `opencode`

这三者不是同一个程序。

它们各自都有：

- 自己的配置文件
- 自己的鉴权文件
- 自己的历史记录
- 自己的模型选择逻辑

### 第 2 层：协议层

工具并不是直接“调用某个模型”，而是先决定用哪种 API 协议：

- OpenAI-compatible
- Anthropic-compatible

这层你可以粗暴理解成：

- OpenAI 风格接口：常见路径像 `/v1/chat/completions`
- Anthropic 风格接口：常见路径像 `/v1/messages`

### 第 3 层：公司网关层

这台机器上，大量请求最后都走到了公司统一网关：

- `https://sub2api.minieye.tech`

或者它的 OpenAI 风格子路径：

- `https://sub2api.minieye.tech/v1`

这就是“统一出口”的含义。

### 第 4 层：真实模型层

真正请求里带的模型名，可能是：

- `gpt-5.5`
- `claude-sonnet-4-6`
- `claude-opus-4-7`
- `claude-haiku-4-5-20251001`

这一层决定：

- 速度
- 成本
- 推理能力
- 输出风格

---

## 3. 最容易误解的一点：同一个公司出口，不等于同一个模型

这是最重要的认知点。

很多人会想：

> 都走 `sub2api.minieye.tech`，那是不是最后其实都一样？

答案是：

**不一定。**

同一个出口，只能说明：

- 都经过公司同一个网关
- 都用公司同一套路由系统
- 都走公司统一的权限/计费/转发层

但这**不能说明**：

- 最后一定是同一个模型
- 不同 `model` 参数一定被强行折叠成同一个后端

工程上更合理的理解是：

- **统一出口 = 从同一个门出去**
- **模型 ID = 出门后你要找哪辆车**

门可以是同一个，但车不一定是同一辆。

---

## 4. 这台机器上目前有哪些工具

当前版本：

- `claude`: `2.1.177`
- `opencode`: `1.17.7`
- `codex`: `0.139.0`

---

## 5. Claude Code 现在是怎么走的

### 5.1 配置文件在哪里

主配置文件：

- [settings.json](/home/mini/.claude/settings.json:1)

### 5.2 现在的关键配置

你当前这台机器上的 `Claude Code` 主要看这些：

- `ANTHROPIC_BASE_URL = https://sub2api.minieye.tech`
- `ANTHROPIC_AUTH_TOKEN = ...`
- 主模型配置是 `claude-sonnet-4-5-20250929`

### 5.3 Claude Code 的调用链路

可以理解成：

1. 你在终端里运行 `claude`
2. `claude` 使用 Anthropic 风格协议
3. 请求打到 `https://sub2api.minieye.tech`
4. 请求里带的是 `claude-*` 这种模型名

所以它本质上是：

- 工具：`Claude Code`
- 协议：Anthropic-compatible
- 网关：`sub2api.minieye.tech`
- 模型：`claude-*`

### 5.4 为什么配置里还能看到 DeepSeek 的名字

在 `~/.claude/settings.json` 里你会看到像这样一些字段：

- `ANTHROPIC_DEFAULT_SONNET_MODEL_NAME = deepseek-v4-pro`

这里的 `...MODEL_NAME` 更像是显示名/别名，不是最底层真实的 provider 模型 ID。

同一个文件里你还能看到真正请求层使用的值：

- `claude-sonnet-4-5-20250929`

所以你可以这样理解：

- 表面展示：可能叫 `deepseek-v4-pro`
- 实际底层请求：还是 `claude-sonnet-4-5-20250929`

---

## 6. Codex 现在是怎么走的

### 6.1 配置文件在哪里

主文件：

- [config.toml](/home/mini/.codex/config.toml:1)
- [auth.json](/home/mini/.codex/auth.json:1)

### 6.2 当前关键配置

Codex 当前是：

- `model_provider = "OpenAI"`
- `model = "gpt-5.4"`
- provider base URL = `https://sub2api.minieye.tech`

`~/.codex/auth.json` 里有：

- `OPENAI_API_KEY`

### 6.3 Codex 的调用链路

可以理解成：

1. 你运行 `codex`
2. `codex` 按 OpenAI 风格协议发请求
3. 请求走 `https://sub2api.minieye.tech`
4. 请求里带模型名 `gpt-5.4`

所以 Codex 这条链路本质是：

- 工具：`Codex`
- 协议：OpenAI-compatible
- 网关：`sub2api.minieye.tech`
- 模型：`gpt-*`

### 6.4 Codex 的重要运行目录

主要在：

- `~/.codex/`

比较重要的文件：

- `config.toml`
- `auth.json`
- `history.jsonl`
- `state_5.sqlite`
- `logs_2.sqlite`
- `goals_1.sqlite`

如果你只是想“迁移配置”，并不一定都要带走。下面会单独讲。

---

## 7. OpenCode 现在是怎么走的

### 7.1 配置文件在哪里

主配置文件：

- [opencode.json](/home/mini/.config/opencode/opencode.json:1)

### 7.2 OpenCode 当前默认模型

当前默认是：

- `minieye-openai-claude/claude-sonnet-4-6`

### 7.3 OpenCode 当前有哪些 provider

当前配置里有 3 套 provider：

1. `minieye-openai-claude`
2. `minieye-anthropic`
3. `minieye`

下面分别解释。

---

### 7.4 `minieye-openai-claude`

这是目前最推荐、也是当前默认的路线。

它的含义是：

- 协议：OpenAI-compatible
- 网关：`https://sub2api.minieye.tech/v1`
- token：公司 Claude token
- 模型：`claude-*`

当前可用模型包括：

- `claude-haiku-4-5-20251001`
- `claude-sonnet-4-5-20250929`
- `claude-sonnet-4-6`
- `claude-opus-4-5-20251101`
- `claude-opus-4-6`
- `claude-opus-4-7`

为什么这条是当前默认：

- 我实测过，它能稳定返回正文
- `opencode run "hi"` 不会出现“只有 banner 没正文”的问题

---

### 7.5 `minieye-anthropic`

这条的含义是：

- 协议：Anthropic-compatible
- 网关：`https://sub2api.minieye.tech`
- token：同一个公司 Claude token
- 模型：也是 `claude-*`

它技术上是可用的，但在这台机器上有一个现实问题：

- 请求确实发出去了
- 网关也确实返回了
- 但 `opencode` 在这条 Anthropic 渲染链路上，有时只显示：
  - `Build · xxx`
- 却不把正文正常显示出来

所以：

- 这条不是“完全坏了”
- 只是当前 `OpenCode + 公司 Anthropic 网关` 组合下，体验不好

因此保留它，但不作为默认。

---

### 7.6 `minieye`

这条是最传统的 OpenAI 风格 GPT 路线：

- 协议：OpenAI-compatible
- 网关：`https://sub2api.minieye.tech/v1`
- token：公司 GPT/OpenAI token
- 模型：
  - `gpt-5.2`
  - `gpt-5.3-codex`
  - `gpt-5.3-codex-spark`
  - `gpt-5.4`
  - `gpt-5.4-mini`
  - `gpt-5.5`

---

## 8. OpenCode 当前推荐怎么用

结合当前实测结果，推荐如下：

### 默认主力

- `minieye-openai-claude/claude-sonnet-4-6`

### 轻量更快

- `minieye-openai-claude/claude-haiku-4-5-20251001`

### 重任务手动切

- `minieye-openai-claude/claude-opus-4-7`

### GPT 路线备用

- `minieye/gpt-5.5`

---

## 9. cc-switch 到底是干什么的

主文件：

- [cc-switch.db](/home/mini/.cc-switch/cc-switch.db)
- [settings.json](/home/mini/.cc-switch/settings.json:1)

`cc-switch` 的作用不是直接发模型请求，而是本地配置中枢。

它主要负责保存：

- provider 定义
- 当前每个 app 选中了哪个 provider
- 通用配置片段
- usage script

比如对 `OpenCode` 来说，当前数据库里有：

- `currentProviderOpencode = minieye-openai-claude`
- `common_config_opencode = ...`

所以你可以把 `cc-switch` 理解成：

> “本地配置控制台”

它能帮 `opencode` / 其他工具切默认 provider，但它本身不回答问题。

---

## 10. ai-forge 到底是干什么的

主文件：

- [config.yaml](/home/mini/.ai-forge/config.yaml:1)

当前里面存的是：

- `intranet.access_key_id`
- `intranet.access_key_secret`

它主要负责：

- 内网登录
- 切订阅组
- 帮你获取公司网关的 token / base URL

所以它更像：

> “账号和订阅组管理工具”

而不是模型运行工具。

---

## 11. 为什么你会觉得“都走 DeepSeek 订阅组，最后是不是都一样”

这个问题特别关键。

你可以这样理解：

### 订阅组解决的是“走哪条公司配额/权限/路由”

比如：

- `default-deepseek`

它更像一个“公司内部的路由套餐/权限套餐”。

### 模型参数解决的是“请求里明确写的是哪个模型”

比如：

- `claude-sonnet-4-6`
- `gpt-5.5`

### 所以二者不是一回事

订阅组说明：

- 你在公司系统里属于哪条配额和转发通道

模型说明：

- 你这次请求到底指定了谁来回答

这就是为什么：

- 同一个 `sub2api.minieye.tech`
- 不同工具仍然会表现不同

---

## 12. 如果你想把这整套环境从 `mini@192.168.16.40` 复制回本地

这里的目标固定为：

**只复制配置，不复制会话记录、历史记录、日志、运行态数据库。**

这是最推荐的方式。

优点：

- 轻
- 干净
- 不容易带来旧会话污染
- 不容易把一堆无意义日志和数据库带过来
- 迁移后不容易误以为“默认模型没改”

### 快速迁移

如果你只是想最快把“能用的这一套”从 `mini@192.168.16.40` 搬回本地，直接按下面做：

#### 第 1 步：目标机器先装好程序

至少保证这三个命令已经存在：

- `claude`
- `codex`
- `opencode`

#### 第 2 步：目标机器创建目录

```bash
mkdir -p ~/.claude ~/.codex ~/.config/opencode ~/.cc-switch ~/.ai-forge
mkdir -p ~/.local/share
```

#### 第 3 步：从旧机器用 rsync 拷最小必需文件

```bash
rsync -av mini@192.168.16.40:~/.claude/settings.json ~/.claude/
rsync -av mini@192.168.16.40:~/.codex/config.toml ~/.codex/
rsync -av mini@192.168.16.40:~/.codex/auth.json ~/.codex/
rsync -av mini@192.168.16.40:~/.config/opencode/opencode.json ~/.config/opencode/
rsync -av mini@192.168.16.40:~/.cc-switch/cc-switch.db ~/.cc-switch/
rsync -av mini@192.168.16.40:~/.cc-switch/settings.json ~/.cc-switch/
rsync -av mini@192.168.16.40:~/.ai-forge/config.yaml ~/.ai-forge/
```

#### 第 4 步：恢复 shell 里的公司内网凭证

把旧机器 shell 配置里的这两行也抄过去：

```bash
export INTRANET_ACCESS_KEY_ID="..."
export INTRANET_ACCESS_KEY_SECRET="..."
```

这台机器上它们原来写在：

- `~/.zshrc`

#### 第 5 步：迁移后立即验证

```bash
claude --version
codex --version
opencode --version
opencode run "hi"
```

如果 `opencode run "hi"` 能正常出正文，就说明最核心链路已经通了。

---

## 13. 最小必拷文件清单（推荐）

如果你只是想让本地也能立刻用起来，最小建议只从 `mini@192.168.16.40` 拷这些配置文件：

### Claude Code

- `~/.claude/settings.json`

### Codex

- `~/.codex/config.toml`
- `~/.codex/auth.json`

### OpenCode

- `~/.config/opencode/opencode.json`

### cc-switch

- `~/.cc-switch/cc-switch.db`
- `~/.cc-switch/settings.json`

### ai-forge

- `~/.ai-forge/config.yaml`

### shell 里的内网凭证

你还要把 shell 配置里的这两行带过去：

- `INTRANET_ACCESS_KEY_ID`
- `INTRANET_ACCESS_KEY_SECRET`

在这台机器上，它们写在：

- `~/.zshrc`

---

## 14. 不要复制的内容

既然目标是“只要配置，不要会话、历史、日志”，下面这些都不要拷：

### Claude Code

- `~/.claude/history.jsonl`
- `~/.claude/sessions/`
- `~/.claude/projects/`
- `~/.claude/cache/`
- `~/.claude/file-history/`

### Codex

- `~/.codex/history.jsonl`
- `~/.codex/state_5.sqlite*`
- `~/.codex/logs_2.sqlite*`
- `~/.codex/goals_1.sqlite*`
- `~/.codex/memories_1.sqlite`
- `~/.codex/sessions/`
- `~/.codex/log/`
- `~/.codex/shell_snapshots/`

### OpenCode

- `~/.local/share/opencode/`
- `~/.config/opencode/node_modules/`

### cc-switch

- `~/.cc-switch/logs/`
- `~/.cc-switch/backups/`

---

## 15. 这些文件在新机器上应该放哪里

尽量保持原路径不变：

- `~/.claude/...`
- `~/.codex/...`
- `~/.config/opencode/opencode.json`
- `~/.cc-switch/...`
- `~/.ai-forge/config.yaml`

如果你路径改了：

- 有些工具仍可能工作
- 但各种本地状态路径可能会不一致

所以最稳妥的方法就是：

**原路径复制到原路径。**

---

## 16. 从 `mini@192.168.16.40` 回本地的最小 rsync 示例

### 先在新机器创建目录

```bash
mkdir -p ~/.claude ~/.codex ~/.config/opencode ~/.cc-switch ~/.ai-forge
```

### 拷最小必需文件

```bash
rsync -av mini@192.168.16.40:~/.claude/settings.json ~/.claude/
rsync -av mini@192.168.16.40:~/.codex/config.toml ~/.codex/
rsync -av mini@192.168.16.40:~/.codex/auth.json ~/.codex/
rsync -av mini@192.168.16.40:~/.config/opencode/opencode.json ~/.config/opencode/
rsync -av mini@192.168.16.40:~/.cc-switch/cc-switch.db ~/.cc-switch/
rsync -av mini@192.168.16.40:~/.cc-switch/settings.json ~/.cc-switch/
rsync -av mini@192.168.16.40:~/.ai-forge/config.yaml ~/.ai-forge/
```

---

## 17. 迁移后最容易出问题的地方

### 1. 目标机器没装程序

你复制配置，不等于复制二进制。

目标机器仍然要安装：

- `claude`
- `codex`
- `opencode`

### 2. 没复制 shell 里的内网凭证

如果你只复制了 `~/.ai-forge/config.yaml`，但没把：

- `INTRANET_ACCESS_KEY_ID`
- `INTRANET_ACCESS_KEY_SECRET`

写回 shell 环境，那么某些需要内网登录的辅助操作还是会失败。

### 3. 不小心复制了旧会话和运行态数据库

尤其是：

- `~/.local/share/opencode/`
- `~/.codex/*.sqlite`

这些会带来旧会话状态，可能让你误以为“默认模型没改”。

### 4. 权限问题

这些文件里有真实 token 和密钥。

迁移后最好确认权限不要太松。

---

## 18. 推荐迁移顺序

如果你想少踩坑，建议按这个顺序做：

1. 在新机器安装：
   - `claude`
   - `codex`
   - `opencode`

2. 只复制最小必需配置文件：
   - `~/.claude/settings.json`
   - `~/.codex/config.toml`
   - `~/.codex/auth.json`
   - `~/.config/opencode/opencode.json`
   - `~/.cc-switch/cc-switch.db`
   - `~/.cc-switch/settings.json`
   - `~/.ai-forge/config.yaml`

3. 恢复 shell 里的内网凭证

4. 测试：
   - `claude`
   - `codex`
   - `opencode run "hi"`

5. 到这里就停，不要复制历史、会话、日志、sqlite 运行态数据库

---

## 19. 最短答案版

如果你只想问：

> “从 `mini@192.168.16.40` 复制这一套环境回本地，最少要拷哪些配置文件？”

答案就是这 7 个：

- `~/.claude/settings.json`
- `~/.codex/config.toml`
- `~/.codex/auth.json`
- `~/.config/opencode/opencode.json`
- `~/.cc-switch/cc-switch.db`
- `~/.cc-switch/settings.json`
- `~/.ai-forge/config.yaml`
