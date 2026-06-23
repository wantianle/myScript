#!/usr/bin/env sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TARGET_DIR=${1:-$SCRIPT_DIR}
TODAY=${TODAY_OVERRIDE:-$(date +%F)}

if [ ! -d "$TARGET_DIR" ]; then
  printf 'Target directory does not exist: %s\n' "$TARGET_DIR" >&2
  exit 1
fi

find "$TARGET_DIR" -mindepth 1 -type f ! -newermt "$TODAY" -delete
find "$TARGET_DIR" -mindepth 1 -type l ! -newermt "$TODAY" -delete
find "$TARGET_DIR" -depth -mindepth 1 -type d -empty -delete
