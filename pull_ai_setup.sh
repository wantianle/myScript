#!/usr/bin/env bash
set -euo pipefail

SRC_HOST="mini@192.168.16.40"

mkdir -p "$HOME/.claude" "$HOME/.codex" "$HOME/.config/opencode" "$HOME/.cc-switch" "$HOME/.ai-forge"

rsync -av "$SRC_HOST:~/.claude/settings.json" "$HOME/.claude/"
rsync -av "$SRC_HOST:~/.codex/config.toml" "$HOME/.codex/"
rsync -av "$SRC_HOST:~/.codex/auth.json" "$HOME/.codex/"
rsync -av "$SRC_HOST:~/.config/opencode/opencode.json" "$HOME/.config/opencode/"
rsync -av "$SRC_HOST:~/.cc-switch/cc-switch.db" "$HOME/.cc-switch/"
rsync -av "$SRC_HOST:~/.cc-switch/settings.json" "$HOME/.cc-switch/"
rsync -av "$SRC_HOST:~/.ai-forge/config.yaml" "$HOME/.ai-forge/"

cat <<'EOF'
配置已从 mini@192.168.16.40 拉取到本地。

已同步：
- ~/.claude/settings.json
- ~/.codex/config.toml
- ~/.codex/auth.json
- ~/.config/opencode/opencode.json
- ~/.cc-switch/cc-switch.db
- ~/.cc-switch/settings.json
- ~/.ai-forge/config.yaml

未同步：
- 会话记录
- 历史记录
- 日志
- sqlite 运行态数据库

建议下一步执行：
- claude --version
- codex --version
- opencode --version
- opencode run "hi"
EOF
