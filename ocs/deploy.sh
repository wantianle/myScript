#!/usr/bin/env bash
# deploy ocs to ~/.local/bin
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)/ocs"
DST="$HOME/.local/bin/ocs"

case "${1:-link}" in
  link)
    rm -f "$DST"
    ln -s "$SRC" "$DST"
    echo "  ✓ ocs → $DST"
    ;;
  copy)
    cp "$SRC" "$DST"
    chmod +x "$DST"
    echo "  ✓ ocs copied to $DST"
    ;;
  *)
    echo "用法: ./deploy.sh [link|copy]"
    exit 1
    ;;
esac
