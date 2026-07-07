# -*- coding: utf-8 -*-
"""配置加载器。

从 ToolConfig 默认值 + 环境变量覆盖构建最终配置。
"""

from __future__ import annotations

import os
from typing import Optional

from bench_smoke.models import ConfigError, ToolConfig


def _env_optional(name: str) -> Optional[str]:
    v = os.environ.get(name, "")
    return v if v else None


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, ""))
    except (ValueError, TypeError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, ""))
    except (ValueError, TypeError):
        return default


def _require_absolute_path(value: str, field: str) -> None:
    if not os.path.isabs(value):
        raise ConfigError(f"'{field}' must be an absolute path, got: {value}")


def _validate_config(cfg: ToolConfig) -> None:
    for name, value in [
        ("run_root", cfg.run_root),
        ("record_root", cfg.record_root),
        ("mount_check_path", cfg.mount_check_path),
    ]:
        _require_absolute_path(value, name)

    if not cfg.playback_topics:
        raise ConfigError("playback_topics must be non-empty")

    for port, label in [(cfg.soc1_port, "soc1_port"), (cfg.soc2_port, "soc2_port")]:
        if not (1 <= int(port) <= 65535):
            raise ConfigError(f"{label} must be in range 1-65535, got {port}")


def load_config() -> ToolConfig:
    """加载配置：默认值 → 环境变量覆盖。

    环境变量（按需设置，均有内建默认值）：
      BENCH_SMOKE_SSH_PASSWORD
      BENCH_SMOKE_SOC1_HOST / BENCH_SMOKE_SOC2_HOST
      BENCH_SMOKE_RUN_ROOT
      BENCH_SMOKE_RECORD_ROOT
      BENCH_SMOKE_MOUNT_CHECK_PATH
      BENCH_SMOKE_COMMAND_TIMEOUT_SEC
      BENCH_SMOKE_RECORDER_EARLY_STOP_OFFSET
    """
    cfg = ToolConfig()

    # --- 环境变量覆盖 ---
    if (pw := _env_optional("BENCH_SMOKE_SSH_PASSWORD")) is not None:
        cfg.ssh_password = pw
    if (h := _env_optional("BENCH_SMOKE_SOC1_HOST")) is not None:
        cfg.soc1_host = h
    if (h := _env_optional("BENCH_SMOKE_SOC2_HOST")) is not None:
        cfg.soc2_host = h
    if (h := _env_optional("BENCH_SMOKE_RUN_ROOT")) is not None:
        cfg.run_root = h
    if (h := _env_optional("BENCH_SMOKE_RECORD_ROOT")) is not None:
        cfg.record_root = h
    if (h := _env_optional("BENCH_SMOKE_MOUNT_CHECK_PATH")) is not None:
        cfg.mount_check_path = h
    cfg.command_timeout_sec = _env_int("BENCH_SMOKE_COMMAND_TIMEOUT_SEC", cfg.command_timeout_sec)
    cfg.recorder_early_stop_offset_sec = _env_float(
        "BENCH_SMOKE_RECORDER_EARLY_STOP_OFFSET", cfg.recorder_early_stop_offset_sec
    )

    _validate_config(cfg)
    return cfg
