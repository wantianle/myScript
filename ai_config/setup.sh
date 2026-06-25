#!/bin/bash
# ============================================
# AI Agent 工具 新电脑一键部署
#   安装 CLI 工具 + ai-forge 认证 + 配置文件 + 密钥
#
# 用法: bash setup.sh [profile]
#   profile 默认 mini, 可选 01297
#
# Claude Code → 官方原生安装器 (curl | bash, 零依赖, 自动更新)
# Codex CLI   → 官方独立安装器 (curl | sh, 零依赖)
# OpenCode    → bun install -g
# CC-Switch   → GitHub .deb
# ai-forge    → 公司 AI 网关 (阿里云 OSS)
# ============================================
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 确保用户级 bin 目录在 PATH 中 (非交互式 bash 不会 source .zshrc)
export PATH="$HOME/.local/bin:$HOME/.bun/bin:$PATH"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROFILE="${1:-mini}"

# --- 环境检测 ---
is_wsl=false
has_gui=false
wsl_need_restart=false
if grep -qi microsoft /proc/version 2>/dev/null || [ -n "$WSL_DISTRO_NAME" ]; then
    is_wsl=true
    # 检测 WSLg (Win11) 或 X Server
    if [ -n "$WAYLAND_DISPLAY" ] || [ -n "$DISPLAY" ]; then
        has_gui=true
    fi
    # WSL 自动启用 systemd (SDWAN / ai-forge 等服务需要)
    if [ -f /etc/wsl.conf ] && grep -q '^systemd=true' /etc/wsl.conf 2>/dev/null; then
        echo -e "${GREEN}[OK]${NC} WSL systemd 已启用"
    else
        echo -e "${YELLOW}[WSL] 启用 systemd...${NC}"
        if [ -f /etc/wsl.conf ]; then
            grep -q '^\[boot\]' /etc/wsl.conf 2>/dev/null || echo -e "\n[boot]" | sudo tee -a /etc/wsl.conf >/dev/null
        else
            echo -e "[boot]" | sudo tee /etc/wsl.conf >/dev/null
        fi
        grep -q '^systemd=true' /etc/wsl.conf 2>/dev/null || echo "systemd=true" | sudo tee -a /etc/wsl.conf >/dev/null
        wsl_need_restart=true
        echo -e "${GREEN}[OK]${NC} 已写入 /etc/wsl.conf (systemd=true)"
    fi
    # 检查 TUN 设备 (SDWAN 隧道需要)
    if [ -c /dev/net/tun ]; then
        echo -e "${GREEN}[OK]${NC} TUN 设备可用 (/dev/net/tun)"
    else
        echo -e "${YELLOW}[WARN]${NC} TUN 设备不可用 — SDWAN 隧道可能无法工作"
    fi
fi

echo "============================================"
echo "  AI Agent 工具 一键部署"
echo "  用户: $PROFILE"
if $is_wsl; then
    if $has_gui; then
        echo "  环境: WSL (GUI 可用)"
    else
        echo "  环境: WSL (纯命令行, CC-Switch 将跳过)"
    fi
fi
echo "============================================"
echo ""

need_source=false

# 提前加载密钥 (ai-forge login 需要)
source "$SCRIPT_DIR/keys/$PROFILE.env"
export MINIEYE_API_KEY CLAUDE_API_KEY OPENAI_API_KEY
export ANTHROPIC_BASE_URL INTRANET_ACCESS_KEY_ID INTRANET_ACCESS_KEY_SECRET
export USERNAME

# ========================================
# 1. Bun (仅 OpenCode 需要)
# ========================================
if ! command -v bun &>/dev/null; then
    echo -e "${YELLOW}[INSTALL] Bun...${NC}"
    curl -fsSL https://bun.sh/install | bash
    need_source=true
    export BUN_INSTALL="$HOME/.bun"
    export PATH="$BUN_INSTALL/bin:$PATH"
fi
echo -e "${GREEN}[OK]${NC} bun $(bun -v 2>/dev/null || echo '(new shell needed)')"

echo ""

# ========================================
# 2. 安装 CLI 工具
# ========================================

# --- Claude Code (npm 安装) ---
if command -v claude &>/dev/null; then
    echo -e "${GREEN}[SKIP]${NC} Claude Code ($(claude --version 2>/dev/null | head -1))"
else
    echo -e "${YELLOW}[INSTALL] Claude Code...${NC}"
    # npm registry 用了 npmmirror, 国内无需科学上网
    if npm install -g @anthropic-ai/claude-code; then
        echo -e "${GREEN}[OK]${NC} Claude Code 安装完成"
    else
        echo -e "${YELLOW}[WARN] Claude Code 安装失败 (上面有错误信息), 跳过${NC}"
    fi
fi

# --- Codex CLI (npm 安装, chatgpt.com 在国内被墙) ---
if command -v codex &>/dev/null; then
    echo -e "${GREEN}[SKIP]${NC} Codex CLI ($(codex --version 2>/dev/null | head -1))"
else
    echo -e "${YELLOW}[INSTALL] Codex CLI...${NC}"
    if npm install -g @openai/codex; then
        echo -e "${GREEN}[OK]${NC} Codex CLI 安装完成"
    else
        echo -e "${YELLOW}[WARN] Codex CLI 安装失败 (上面有错误信息), 跳过${NC}"
    fi
fi

# --- OpenCode (bun) ---
if command -v opencode &>/dev/null; then
    echo -e "${GREEN}[SKIP]${NC} OpenCode ($(opencode --version 2>/dev/null))"
else
    echo -e "${YELLOW}[INSTALL] OpenCode...${NC}"
    bun install -g opencode-ai
    echo -e "${GREEN}[OK]${NC} OpenCode 安装完成"
fi

# --- CC-Switch (GitHub .deb, 需要 GUI) ---
if command -v cc-switch &>/dev/null; then
    echo -e "${GREEN}[SKIP]${NC} CC-Switch ($(cc-switch --version 2>/dev/null))"
elif $is_wsl && ! $has_gui; then
    echo -e "${YELLOW}[SKIP]${NC} CC-Switch — WSL 无 GUI, 跳过 (托盘程序需要 WSLg 或 X Server)"
else
    echo -e "${YELLOW}[INSTALL] CC-Switch...${NC}"
    LATEST_URL=$(curl -s https://api.github.com/repos/farion1231/cc-switch/releases/latest \
        | grep "browser_download_url" | grep "\.deb" | head -1 | cut -d'"' -f4)
    if [ -n "$LATEST_URL" ] && command -v sudo &>/dev/null; then
        wget -q "$LATEST_URL" -O /tmp/cc-switch.deb
        sudo dpkg -i /tmp/cc-switch.deb
        rm -f /tmp/cc-switch.deb
        echo -e "${GREEN}[OK]${NC} CC-Switch 安装完成"
    else
        echo -e "${YELLOW}[WARN] 无 sudo 权限，跳过 CC-Switch. 手动: https://github.com/farion1231/cc-switch/releases${NC}"
    fi
fi

# --- ai-forge (公司 AI 网关) ---
if command -v ai-forge &>/dev/null; then
    echo -e "${GREEN}[SKIP]${NC} ai-forge ($(ai-forge --version 2>/dev/null))"
else
    echo -e "${YELLOW}[INSTALL] ai-forge (公司 AI 网关)...${NC}"
    curl -fsSL https://go-self-update.oss-cn-shenzhen.aliyuncs.com/ai-forge/latest/install.sh | bash
    echo -e "${GREEN}[OK]${NC} ai-forge 安装完成"
fi

echo ""

# ========================================
# 3. ai-forge 登录认证
#   - 写入环境变量到 shell rc
#   - 使 Claude Code / Codex 走公司后端
# ========================================
echo ">>> ai-forge 认证..."
if [ -n "$INTRANET_ACCESS_KEY_ID" ] && [ -n "$INTRANET_ACCESS_KEY_SECRET" ]; then
    ai-forge login -i "$INTRANET_ACCESS_KEY_ID" -s "$INTRANET_ACCESS_KEY_SECRET"
    ai-forge login -i "$INTRANET_ACCESS_KEY_ID" -s "$INTRANET_ACCESS_KEY_SECRET" -p codex
    echo -e "${GREEN}[OK]${NC} ai-forge 认证完成 (Claude Code + Codex)"
else
    echo -e "${YELLOW}[WARN] 缺少 INTRANET_ACCESS_KEY_ID/SECRET, 跳过 ai-forge 登录${NC}"
fi

echo ""

# ========================================
# 4. 部署配置文件
# ========================================
echo ">>> 部署配置文件..."
bash "$SCRIPT_DIR/install.sh" "$PROFILE"

echo ""

# ========================================
# 5. 收尾
# ========================================
echo "============================================"
echo "  全部完成!"
if $is_wsl && ! $has_gui; then
    echo "  (CC-Switch 已跳过 — WSL 无 GUI)"
fi
echo "============================================"
echo ""
echo "已安装:"
echo "  claude     $(claude --version 2>/dev/null | head -1 || echo '?')"
echo "  codex      $(codex --version 2>/dev/null | head -1 || echo '?')"
echo "  opencode   $(opencode --version 2>/dev/null || echo '?')"
if command -v cc-switch &>/dev/null; then
    echo "  cc-switch  $(cc-switch --version 2>/dev/null || echo '?')"
fi
echo "  ai-forge   $(ai-forge --version 2>/dev/null || echo '?')"
echo ""
if $need_source; then
    echo -e "${YELLOW}⚠ 首次安装 Bun, 请执行: source ~/.zshrc${NC}"
fi
if $is_wsl; then
    echo -e "${YELLOW}💡 WSL 提示: 如果 WSLg 未启用, 升级到 Win11 或安装 X Server (VcXsrv/MobaXterm) 后可单独安装 CC-Switch${NC}"
fi
if $wsl_need_restart; then
    echo ""
    echo -e "${YELLOW}⚠ WSL systemd 刚被启用, 请在 PowerShell 执行以下命令重启 WSL:${NC}"
    echo "   wsl --shutdown"
    echo "   然后重新打开 WSL 终端, systemd 即可生效"
fi
