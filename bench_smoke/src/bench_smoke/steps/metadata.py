"""录制完成后采集版本信息和 mcap 元数据。"""

import logging
import shlex
from datetime import datetime, timezone
from typing import Dict, List

from .. import env
from ..command_runner import CommandExecutionError, run_remote
from ..config import ToolConfig
from ..models import CommandResult, RunContext, StepResult, StepStatus

logger = logging.getLogger(__name__)


def collect_metadata(context: RunContext, config: ToolConfig) -> StepResult:
    """采集回灌后元数据。

    1. 对 soc1 执行 ``vmc list``（信息性追踪，容忍失败）。
    2. 在 soc2 上对每个生成的 .mcap 执行 ``mkit info``。
    """
    started_at = datetime.now(timezone.utc)
    commands: List[CommandResult] = []

    generated_mcaps = context.generated_mcaps

    try:
        if not generated_mcaps:
            raise RuntimeError("No generated .mcap files in RunContext")

        logger.info("Collecting version info via vmc list on soc1")
        version_result = run_remote(
            host=config.soc1_host,
            port=config.soc1_port,
            user=config.soc1_user,
            password=config.ssh_password,
            remote_command="vmc list || true",
            timeout_sec=config.command_timeout_sec,
            check=False,
        )
        commands.append(version_result)
        version_info = version_result.stdout.strip()

        mcap_info: Dict[str, str] = {}
        for mcap_path in generated_mcaps:
            logger.info("Running mkit info on %s", mcap_path)
            info_cmd = env.shell_init() + env.mkit_bin() + " info {}".format(
                shlex.quote(mcap_path)
            )
            info_result = run_remote(
                host=config.soc2_host,
                port=config.soc2_port,
                user=config.soc2_user,
                password=config.ssh_password,
                remote_command=info_cmd,
                timeout_sec=config.command_timeout_sec,
                check=True,
            )
            commands.append(info_result)
            mcap_info[mcap_path] = info_result.stdout.strip()
            logger.info(
                "mkit info completed for %s (%d bytes of output)",
                mcap_path,
                len(info_result.stdout),
            )

    except CommandExecutionError as exc:
        ended_at = datetime.now(timezone.utc)
        duration_sec = (ended_at - started_at).total_seconds()
        logger.error("Metadata collection failed: %s", exc)
        return StepResult(
            name="collect_metadata",
            status=StepStatus.FAILED,
            started_at=started_at.isoformat(),
            ended_at=ended_at.isoformat(),
            duration_sec=duration_sec,
            message="Metadata collection failed: {}".format(exc),
            commands=commands,
            artifacts={"generated_mcaps": generated_mcaps},
            error_type=type(exc).__name__,
        )

    except RuntimeError as exc:
        ended_at = datetime.now(timezone.utc)
        duration_sec = (ended_at - started_at).total_seconds()
        logger.error("Metadata collection guard failed: %s", exc)
        return StepResult(
            name="collect_metadata",
            status=StepStatus.FAILED,
            started_at=started_at.isoformat(),
            ended_at=ended_at.isoformat(),
            duration_sec=duration_sec,
            message="Metadata collection failed: {}".format(exc),
            commands=commands,
            artifacts={"generated_mcaps": generated_mcaps},
            error_type="GuardFailure",
        )

    except Exception as exc:
        ended_at = datetime.now(timezone.utc)
        duration_sec = (ended_at - started_at).total_seconds()
        logger.exception("Unexpected error during metadata collection")
        return StepResult(
            name="collect_metadata",
            status=StepStatus.FAILED,
            started_at=started_at.isoformat(),
            ended_at=ended_at.isoformat(),
            duration_sec=duration_sec,
            message="Unexpected error: {}".format(exc),
            commands=commands,
            artifacts={"generated_mcaps": generated_mcaps},
            error_type="UnexpectedError",
        )

    ended_at = datetime.now(timezone.utc)
    duration_sec = (ended_at - started_at).total_seconds()

    return StepResult(
        name="collect_metadata",
        status=StepStatus.SUCCESS,
        started_at=started_at.isoformat(),
        ended_at=ended_at.isoformat(),
        duration_sec=duration_sec,
        message="Metadata collected for {} .mcap file(s)".format(
            len(generated_mcaps)
        ),
        commands=commands,
        artifacts={
            "version_info": version_info,
            "mcap_info": mcap_info,
            "generated_mcaps": generated_mcaps,
        },
    )
