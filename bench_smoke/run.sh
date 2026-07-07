#!/usr/bin/env bash
# bench_smoke CLI 入口
# =====================
# 用法:
#   # 默认全流程（使用 ./datasets.yaml 作为清单）
#   ./run.sh
#
#   # 指定数据集
#   ./run.sh --dataset-id 7037566695
#   ./run.sh --dataset-id 7037566695,7037600648
#
#   # 单步排障
#   ./run.sh debug playback
#   ./run.sh debug playback --dataset-id 7037566695
#
#   # 透传任意参数
#   ./run.sh run --manifest other-datasets.yaml --package mdrive=1.2.3
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$ROOT/src:${PYTHONPATH:-}"
# 默认产物输出到工具内部 output/ 目录
export BENCH_SMOKE_RUN_ROOT="${BENCH_SMOKE_RUN_ROOT:-$ROOT/output}"

if [ -x /usr/bin/python3 ]; then
  PYTHON_BIN="/usr/bin/python3"
else
  PYTHON_BIN="$(command -v python3)"
fi

# 加载固定配置
if [ -f "$ROOT/settings.sh" ]; then
  source "$ROOT/settings.sh"
fi

if [ $# -eq 0 ]; then
  # 无参默认: 使用内置 datasets.yaml 执行全流程
  exec "$PYTHON_BIN" -m bench_smoke.cli run --manifest "$ROOT/datasets.yaml"
elif [ "$1" = "clean" ]; then
  RUNS_DIR="${BENCH_SMOKE_RUN_ROOT:-$ROOT/output}/runs"
  if [ -d "$RUNS_DIR" ]; then
    rm -rf "$RUNS_DIR"
    mkdir -p "$RUNS_DIR"
    echo "Cleaned $RUNS_DIR"
  else
    echo "No runs directory found at $RUNS_DIR"
  fi
  exit 0
elif [ "$1" = "debug" ]; then
  shift
  # debug 模式: 自动补 --manifest
  exec "$PYTHON_BIN" -m bench_smoke.cli debug --manifest "$ROOT/datasets.yaml" "$@"
elif [ "$1" = "run" ]; then
  shift
  if echo "$*" | grep -q '\--manifest'; then
    exec "$PYTHON_BIN" -m bench_smoke.cli run "$@"
  else
    exec "$PYTHON_BIN" -m bench_smoke.cli run --manifest "$ROOT/datasets.yaml" "$@"
  fi
else
  # 直接透传（如 --dataset-id xxx 等效于 run --dataset-id xxx）
  exec "$PYTHON_BIN" -m bench_smoke.cli run --manifest "$ROOT/datasets.yaml" "$@"
fi
