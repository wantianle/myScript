"""通过 supervisor-managed Recorder 服务在 soc2 上控制录制。

使用 supervisorctl start/stop Recorder 管理生命周期，
通过时间戳标记 + find -newer 发现生成的 .mcap 文件。
"""

import logging
import os
import shlex
from datetime import datetime, timezone
from typing import List, Tuple

from .. import env
from ..command_runner import CommandExecutionError, run_remote
from ..config import ToolConfig
from ..models import CommandResult, RunContext, StepResult, StepStatus

logger = logging.getLogger(__name__)

# soc2 上的时间戳标记文件：在 Recorder 启动前创建，
# 以便 stop_recorder 通过 find -newer 发现新生成的 .mcap 文件。
_RECORDER_START_TIME_FILE = "/tmp/bench_smoke_record_start.txt"


def start_recorder(context: RunContext, config: ToolConfig) -> StepResult:
    """在 soc2 上启动 supervisor 管理的 Recorder 服务。

    supervisor 管理的 Recorder 写入自己的时间戳目录
    （record_YYMMDD_hhmmss），输出路径由实际发现文件决定。

    1. 放置时间戳标记文件。
    2. 捕获 vmc list 版本追踪。
    3. 通过 supervisorctl 启动 Recorder。
    """
    started_at = datetime.now(timezone.utc)
    commands: List[CommandResult] = []

    try:
        touch_cmd = "touch {}".format(shlex.quote(_RECORDER_START_TIME_FILE))
        touch_result = run_remote(
            host=config.soc2_host, port=config.soc2_port,
            user=config.soc2_user, password=config.ssh_password,
            remote_command=touch_cmd,
            timeout_sec=config.command_timeout_sec, check=True,
        )
        commands.append(touch_result)

        logger.info("Capturing package version trace on soc2")
        version_result = run_remote(
            host=config.soc2_host, port=config.soc2_port,
            user=config.soc2_user, password=config.ssh_password,
            remote_command=env.shell_init() + "vmc list > /tmp/package_version.txt 2>&1 || true",
            timeout_sec=config.command_timeout_sec, check=True,
        )
        commands.append(version_result)

        start_cmd = "sudo supervisorctl start Recorder"
        logger.info("Starting Recorder service on soc2")
        start_result = run_remote(
            host=config.soc2_host, port=config.soc2_port,
            user=config.soc2_user, password=config.ssh_password,
            remote_command=start_cmd,
            timeout_sec=config.recorder_start_timeout_sec, check=True,
        )
        commands.append(start_result)

        logger.info("Recorder service started on soc2")

    except CommandExecutionError as exc:
        ended_at = datetime.now(timezone.utc)
        duration_sec = (ended_at - started_at).total_seconds()
        logger.error("Failed to start recorder: %s", exc)
        return StepResult(
            name="start_recorder", status=StepStatus.FAILED,
            started_at=started_at.isoformat(), ended_at=ended_at.isoformat(),
            duration_sec=duration_sec,
            message="Failed to start recorder: {}".format(exc),
            commands=commands,
            artifacts={"recorder_host": "soc2"},
            error_type=type(exc).__name__,
        )

    except RuntimeError as exc:
        ended_at = datetime.now(timezone.utc)
        duration_sec = (ended_at - started_at).total_seconds()
        logger.error("Recorder launch guard failed: %s", exc)
        return StepResult(
            name="start_recorder", status=StepStatus.FAILED,
            started_at=started_at.isoformat(), ended_at=ended_at.isoformat(),
            duration_sec=duration_sec,
            message="Failed to start recorder: {}".format(exc),
            commands=commands,
            artifacts={"recorder_host": "soc2"},
            error_type="GuardFailure",
        )

    except Exception as exc:
        ended_at = datetime.now(timezone.utc)
        duration_sec = (ended_at - started_at).total_seconds()
        logger.exception("Unexpected error starting recorder")
        return StepResult(
            name="start_recorder", status=StepStatus.FAILED,
            started_at=started_at.isoformat(), ended_at=ended_at.isoformat(),
            duration_sec=duration_sec,
            message="Unexpected error: {}".format(exc),
            commands=commands,
            artifacts={"recorder_host": "soc2"},
            error_type="UnexpectedError",
        )

    ended_at = datetime.now(timezone.utc)
    duration_sec = (ended_at - started_at).total_seconds()

    return StepResult(
        name="start_recorder", status=StepStatus.SUCCESS,
        started_at=started_at.isoformat(), ended_at=ended_at.isoformat(),
        duration_sec=duration_sec,
        message="Recorder service started on soc2",
        commands=commands,
        artifacts={"recorder_host": "soc2"},
    )


def _discover_mcaps_by_time(config: ToolConfig) -> Tuple[List[str], CommandResult]:
    """通过 find -newer 发现录制期间新生成的 .mcap 文件。

    实际输出目录由发现文件派生，而非预先推测。
    """
    find_cmd = (
        "find {} -name '*.mcap' -type f -newer {} 2>/dev/null || true"
    ).format(
        shlex.quote(config.record_root),
        shlex.quote(_RECORDER_START_TIME_FILE),
    )
    find_result = run_remote(
        host=config.soc2_host, port=config.soc2_port,
        user=config.soc2_user, password=config.ssh_password,
        remote_command=find_cmd,
        timeout_sec=config.command_timeout_sec, check=False,
    )
    mcaps = [
        line.strip()
        for line in find_result.stdout.splitlines()
        if line.strip().endswith(".mcap")
    ]
    return mcaps, find_result


def stop_recorder(context: RunContext, config: ToolConfig) -> StepResult:
    """停止 Recorder 服务并发现生成的 .mcap 文件。

    1. 通过 supervisorctl 停止 Recorder。
    2. 通过 find -newer 发现录制期间创建的文件。
    3. 由第一个发现的 .mcap 文件推断输出目录。
    """
    started_at = datetime.now(timezone.utc)
    commands: List[CommandResult] = []

    record_output_dir = context.record_output_dir

    try:
        stop_cmd = "sudo supervisorctl stop Recorder"
        logger.info("Stopping Recorder service on soc2")
        stop_result = run_remote(
            host=config.soc2_host, port=config.soc2_port,
            user=config.soc2_user, password=config.ssh_password,
            remote_command=stop_cmd,
            timeout_sec=config.recorder_stop_timeout_sec, check=False,
        )
        commands.append(stop_result)
        logger.info(
            "Recorder stop returned rc=%d: %s",
            stop_result.return_code, stop_result.stdout.strip(),
        )

        logger.info("Discovering .mcap files under %s", config.record_root)
        generated_mcaps, find_result = _discover_mcaps_by_time(config)
        commands.append(find_result)

        if not generated_mcaps:
            raise RuntimeError(
                "No .mcap files found under {} newer than {}".format(
                    config.record_root, _RECORDER_START_TIME_FILE
                )
            )

        discovered_dir = os.path.dirname(generated_mcaps[0])
        context.record_output_dir = discovered_dir
        context.generated_mcaps = generated_mcaps

        logger.info(
            "Found %d .mcap file(s) in %s: %s",
            len(generated_mcaps), discovered_dir, generated_mcaps,
        )

    except CommandExecutionError as exc:
        ended_at = datetime.now(timezone.utc)
        duration_sec = (ended_at - started_at).total_seconds()
        logger.error("Failed to stop recorder: %s", exc)
        return StepResult(
            name="stop_recorder", status=StepStatus.FAILED,
            started_at=started_at.isoformat(), ended_at=ended_at.isoformat(),
            duration_sec=duration_sec,
            message="Failed to stop recorder: {}".format(exc),
            commands=commands,
            artifacts={
                "record_output_dir": record_output_dir,
                "generated_mcaps": context.generated_mcaps,
            },
            error_type=type(exc).__name__,
        )

    except RuntimeError as exc:
        ended_at = datetime.now(timezone.utc)
        duration_sec = (ended_at - started_at).total_seconds()
        logger.error("Recorder stop guard failed: %s", exc)
        return StepResult(
            name="stop_recorder", status=StepStatus.FAILED,
            started_at=started_at.isoformat(), ended_at=ended_at.isoformat(),
            duration_sec=duration_sec,
            message="Failed to stop recorder: {}".format(exc),
            commands=commands,
            artifacts={
                "record_output_dir": record_output_dir,
                "generated_mcaps": context.generated_mcaps,
            },
            error_type="GuardFailure",
        )

    except Exception as exc:
        ended_at = datetime.now(timezone.utc)
        duration_sec = (ended_at - started_at).total_seconds()
        logger.exception("Unexpected error stopping recorder")
        return StepResult(
            name="stop_recorder", status=StepStatus.FAILED,
            started_at=started_at.isoformat(), ended_at=ended_at.isoformat(),
            duration_sec=duration_sec,
            message="Unexpected error: {}".format(exc),
            commands=commands,
            artifacts={
                "record_output_dir": record_output_dir,
                "generated_mcaps": context.generated_mcaps,
            },
            error_type="UnexpectedError",
        )

    ended_at = datetime.now(timezone.utc)
    duration_sec = (ended_at - started_at).total_seconds()

    return StepResult(
        name="stop_recorder", status=StepStatus.SUCCESS,
        started_at=started_at.isoformat(), ended_at=ended_at.isoformat(),
        duration_sec=duration_sec,
        message="Recorder stopped; {} .mcap file(s) found in {}".format(
            len(generated_mcaps), discovered_dir
        ),
        commands=commands,
        artifacts={
            "record_output_dir": discovered_dir,
            "generated_mcaps": generated_mcaps,
            "mcap_host": "soc2",
        },
    )
