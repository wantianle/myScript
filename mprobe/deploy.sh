#!/usr/bin/env bash
# deploy mprobe to ~/.local/bin
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)/mprobe.py"
DST="$HOME/.local/bin/mprobe"

case "${1:-link}" in
  link)
    rm -f "$DST"
    ln -s "$SRC" "$DST"
    chmod +x "$SRC"
    echo "  ✓ mprobe → $DST"
    ;;
  copy)
    cp "$SRC" "$DST"
    chmod +x "$DST"
    echo "  ✓ mprobe copied to $DST"
    ;;
  *)
    echo "用法: ./deploy.sh [link|copy]"
    exit 1
    ;;
esac
