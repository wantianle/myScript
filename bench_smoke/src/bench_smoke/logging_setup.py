# -*- coding: utf-8 -*-
"""日志配置。

统一格式，支持终端（stderr）和文件输出。每次运行有独立的 run.log。
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Optional


_LOG_FORMAT = (
    "%(asctime)s.%(msecs)03d | %(levelname)-8s | "
    "%(name)s | %(message)s"
)
_LOG_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"

_LOGGER = logging.getLogger("bench_smoke")


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """返回 bench_smoke 层级下的 logger。

    Args:
        name: 可选的后缀，如 "manifest"。None 时返回根 logger。
    """
    if name:
        return logging.getLogger(f"bench_smoke.{name}")
    return _LOGGER


def setup_logging(
    run_dir: str,
    level: int = logging.DEBUG,
    console: bool = True,
) -> logging.Logger:
    """初始化日志。

    Args:
        run_dir: 运行目录，run.log 将写入此处。为空字符串时仅输出到终端。
        level:   日志级别，默认 DEBUG。
        console: 是否同时输出到 stderr。
    """
    root = _LOGGER
    root.setLevel(level)

    if root.handlers:
        root.handlers.clear()

    # 文件 handler（仅当 run_dir 非空时启用）
    if run_dir:
        os.makedirs(run_dir, exist_ok=True)
        log_path = os.path.join(run_dir, "run.log")
        file_h = logging.FileHandler(log_path, encoding="utf-8")
        file_h.setLevel(level)
        file_h.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATE_FORMAT))
        root.addHandler(file_h)

    # 终端 handler
    if console:
        console_h = logging.StreamHandler(sys.stderr)
        console_h.setLevel(logging.INFO)
        console_h.setFormatter(
            logging.Formatter("%(levelname)-8s | %(name)s | %(message)s")
        )
        root.addHandler(console_h)

    root.info("Logging initialised — run_dir=%s", run_dir)
    return root
