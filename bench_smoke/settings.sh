#!/usr/bin/env bash
# bench_smoke 固定配置
# ======================
# 由 run.sh 自动 source。取消注释即可覆盖默认值。
# 所有值均有内建默认值，只需设置与默认不同的项。

# --- SSH 连接 ---
export BENCH_SMOKE_SSH_PASSWORD='mini!@#123.com'
export BENCH_SMOKE_SOC1_HOST='192.168.10.2'
export BENCH_SMOKE_SOC2_HOST='localhost'

# --- 可选的覆盖项（按需取消注释） ---
# export BENCH_SMOKE_RUN_ROOT='/path/to/output'            # 默认: $ROOT/output
# export BENCH_SMOKE_RECORD_ROOT='/mdrive_data/bag'       # Recorder 落盘路径
# export BENCH_SMOKE_MOUNT_CHECK_PATH='/media/nas'        # NAS 挂载检查路径
# export BENCH_SMOKE_COMMAND_TIMEOUT_SEC=30               # 单条命令超时(秒)
# export BENCH_SMOKE_PLAYBACK_TOPICS="/t1,/t2,/t3"         # 回灌 topic (逗号分隔，覆盖内置默认)
