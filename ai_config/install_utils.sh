#!/bin/bash
# ============================================
# AI Config 安装工具函数
# 用法: source install_utils.sh
# ============================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

FORCE="${FORCE:-0}"

# 安全复制文件: 目标存在时对比大小并询问
# 用法: safe_copy <src> <dst> [描述]
safe_copy() {
    local src="$1"
    local dst="$2"
    local desc="${3:-$(basename "$dst")}"

    if [ -f "$dst" ]; then
        local src_size=$(stat -c%s "$src" 2>/dev/null || echo 0)
        local dst_size=$(stat -c%s "$dst" 2>/dev/null || echo 0)
        local diff=$((src_size - dst_size))

        printf "  ${CYAN}[存在]${NC} %-40s  " "$desc"
        if [ "$src_size" -eq "$dst_size" ]; then
            echo -e "${GREEN}大小相同${NC} (${src_size}B), 跳过"
            return 0
        fi

        printf "旧:${RED}%sB${NC} → 新:${GREEN}%sB${NC}  " "$dst_size" "$src_size"
        if [ "$diff" -gt 0 ]; then
            echo -en "${RED}+${diff}B${NC}"
        elif [ "$diff" -lt 0 ]; then
            echo -en "${GREEN}${diff}B${NC}"
        else
            echo -en "无变化"
        fi
        echo ""

        if [ "$FORCE" -eq 1 ]; then
            echo "    ${YELLOW}强制覆盖 (-f)${NC}"
        else
            read -r -p "    覆盖? [y/N] " answer
            if [ "$answer" != "y" ] && [ "$answer" != "Y" ]; then
                echo "    ${YELLOW}跳过${NC}"
                return 0
            fi
        fi
    fi

    cp "$src" "$dst"
    echo -e "    ${GREEN}✓${NC} 已安装"
}

# 安全 sed 写入: 目标存在时对比大小并询问
# 用法: safe_sed <template_src> <dst> <sed_expr>... [-- 描述]
safe_sed_write() {
    local template="$1"
    local dst="$2"
    shift 2
    local desc="${@: -1}"  # 最后一个参数是描述
    local sed_args=("${@:1:$#-1}")

    local tmp="/tmp/ai_config_install_$$"
    sed "${sed_args[@]}" "$template" > "$tmp"

    if [ -f "$dst" ]; then
        local tmp_size=$(stat -c%s "$tmp" 2>/dev/null || echo 0)
        local dst_size=$(stat -c%s "$dst" 2>/dev/null || echo 0)
        local diff=$((tmp_size - dst_size))

        printf "  ${CYAN}[存在]${NC} %-40s  " "$desc"
        if [ "$tmp_size" -eq "$dst_size" ]; then
            echo -e "${GREEN}大小相同${NC} (${tmp_size}B), 跳过"
            rm -f "$tmp"
            return 0
        fi

        printf "旧:${RED}%sB${NC} → 新:${GREEN}%sB${NC}  " "$dst_size" "$tmp_size"
        if [ "$diff" -gt 0 ]; then
            echo -en "${RED}+${diff}B${NC}"
        elif [ "$diff" -lt 0 ]; then
            echo -en "${GREEN}${diff}B${NC}"
        fi
        echo ""

        if [ "$FORCE" -eq 1 ]; then
            echo "    ${YELLOW}强制覆盖 (-f)${NC}"
        else
            read -r -p "    覆盖? [y/N] " answer
            if [ "$answer" != "y" ] && [ "$answer" != "Y" ]; then
                echo "    ${YELLOW}跳过${NC}"
                rm -f "$tmp"
                return 0
            fi
        fi
    fi

    mv "$tmp" "$dst"
    echo -e "    ${GREEN}✓${NC} 已安装"
}
