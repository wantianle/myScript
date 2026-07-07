"""使用 mkit play 的单次回灌。

强制禁止 MVP 循环模式，显式展开通配符为具体 mcap 文件。
同时提供 build_playback_command() 供编排器以子进程方式后台启动回灌。
"""

import glob as _glob
import logging
import os
import re as _re
import shlex
import subprocess as _sp
from datetime import datetime, timezone
from typing import FrozenSet, List, Optional, Tuple

from .. import env
from ..command_runner import CommandExecutionError, run_local
from ..config import ToolConfig
from ..models import CommandResult, RunContext, StepResult, StepStatus

logger = logging.getLogger(__name__)

_FORBIDDEN_LOOP_FLAGS: FrozenSet[str] = frozenset({"-l", "--loop"})


def _validate(context: RunContext, config: ToolConfig) -> Tuple[List[str], str]:
    """校验回灌前提条件，构建命令并返回 (argv, local_path)。"""
    local_path = context.local_dataset_path
    if not local_path:
        raise RuntimeError("local_dataset_path is not set on RunContext")
    if not config.playback_topics:
        raise RuntimeError("playback_topics is empty in configuration")
    for topic in config.playback_topics:
        if topic in _FORBIDDEN_LOOP_FLAGS:
            raise RuntimeError(
                "Loop flag '{}' is forbidden in MVP playback".format(topic)
            )

    concrete_files = sorted(_glob.glob(os.path.join(local_path, "*.mcap")))
    if not concrete_files:
        raise RuntimeError(
            "No .mcap files under {}".format(local_path)
        )

    play_args = (
        env.mkit_bin() + " play -c "
        + " ".join(shlex.quote(t) for t in config.playback_topics)
        + " "
        + " ".join("-f " + shlex.quote(f) for f in concrete_files)
    )
    return (["bash", "-c", env.shell_init() + play_args], local_path)


def play_once(context: RunContext, config: ToolConfig) -> StepResult:
    """对本地化的数据集执行单次 mkit play 回灌（阻塞式）。"""
    t0 = datetime.now(timezone.utc)
    commands: List[CommandResult] = []
    local_path = context.local_dataset_path

    try:
        cmd, local_path = _validate(context, config)
        logger.info("Starting playback: local_path=%s, topics=%s",
                     local_path, config.playback_topics)
        pr = run_local(cmd, timeout_sec=config.playback_timeout_sec,
                       check=True, cwd=local_path)
        commands.append(pr)
        logger.info("Playback completed (rc=%d, elapsed=%.1fs)",
                     pr.return_code, pr.duration_sec)
    except CommandExecutionError as exc:
        t1 = datetime.now(timezone.utc)
        logger.error("Playback failed: %s", exc)
        return StepResult(
            name="playback", status=StepStatus.FAILED,
            started_at=t0.isoformat(), ended_at=t1.isoformat(),
            duration_sec=(t1 - t0).total_seconds(),
            message="Playback failed: {}".format(exc),
            commands=commands,
            artifacts={"local_dataset_path": local_path or "",
                        "topics": list(config.playback_topics),
                        "loop_enabled": False},
            error_type=type(exc).__name__,
        )
    except RuntimeError as exc:
        t1 = datetime.now(timezone.utc)
        logger.error("Playback guard failed: %s", exc)
        return StepResult(
            name="playback", status=StepStatus.FAILED,
            started_at=t0.isoformat(), ended_at=t1.isoformat(),
            duration_sec=(t1 - t0).total_seconds(),
            message="Playback failed: {}".format(exc),
            commands=commands,
            artifacts={"local_dataset_path": local_path or "",
                        "topics": list(config.playback_topics),
                        "loop_enabled": False},
            error_type="GuardFailure",
        )
    except Exception as exc:
        t1 = datetime.now(timezone.utc)
        logger.exception("Unexpected error during playback")
        return StepResult(
            name="playback", status=StepStatus.FAILED,
            started_at=t0.isoformat(), ended_at=t1.isoformat(),
            duration_sec=(t1 - t0).total_seconds(),
            message="Unexpected error: {}".format(exc),
            commands=commands,
            artifacts={"local_dataset_path": local_path or "",
                        "topics": list(config.playback_topics),
                        "loop_enabled": False},
            error_type="UnexpectedError",
        )

    t1 = datetime.now(timezone.utc)
    return StepResult(
        name="playback", status=StepStatus.SUCCESS,
        started_at=t0.isoformat(), ended_at=t1.isoformat(),
        duration_sec=(t1 - t0).total_seconds(),
        message="Playback completed successfully",
        commands=commands,
        artifacts={"local_dataset_path": local_path,
                    "topics": list(config.playback_topics),
                    "loop_enabled": False},
    )


def build_playback_command(
    context: RunContext, config: ToolConfig
) -> Tuple[List[str], str]:
    """构建回灌命令并返回 (argv, local_path)。

    供编排器用于后台启动回灌子进程，以便与录制重叠执行。
    """
    return _validate(context, config)


_DURATION_RE = _re.compile(r"Duration:\s+([\d.]+)\s+seconds")


def get_playback_duration(context: RunContext, config: ToolConfig) -> Optional[float]:
    """通过 mkit info 探测本地化回灌输入文件的预期时长（秒）。"""
    local_path = context.local_dataset_path
    if not local_path or not os.path.isdir(local_path):
        return None
    mcaps = sorted(_glob.glob(os.path.join(local_path, "*.mcap")))
    if not mcaps:
        return None
    target = mcaps[0]
    logger.info("Probing playback duration from %s", target)
    cmd = ["bash", "-c", env.shell_init() + env.mkit_bin() + " info " + shlex.quote(target)]
    try:
        proc = _sp.run(cmd, capture_output=True, text=True,
                       timeout=config.command_timeout_sec)
        if proc.returncode != 0:
            return None
        match = _DURATION_RE.search(proc.stdout)
        if match:
            dur = float(match.group(1))
            logger.info("Expected playback duration: %.1f seconds", dur)
            return dur
        return None
    except Exception as exc:
        logger.warning("Failed to probe playback duration: %s", exc)
        return None
