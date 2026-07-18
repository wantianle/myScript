"""通过 SSH supervisorctl 控制 soc1/soc2 的底软模块。"""

import logging
import shlex
from datetime import datetime, timezone
from typing import Dict, List, Optional

from ..command_runner import CommandExecutionError, run_remote
from ..config import ToolConfig
from ..models import CommandResult, RunContext, StepResult, StepStatus

logger = logging.getLogger(__name__)


def _extract_failed_module(commands: List[CommandResult]) -> Optional[str]:
    """从最后一条命令的 display_command 中提取 supervisorctl 操作的模块名。"""
    if not commands:
        return None
    last_display = commands[-1].display_command
    for prefix in ("sudo supervisorctl stop ", "sudo supervisorctl start "):
        if prefix in last_display:
            return last_display.split(prefix, 1)[1].split()[0].strip()
    return None


def _stop_modules(
    host: str, port: int, user: str,
    modules: List[str], timeout_sec: int,
    soc_label: str, ssh_password: Optional[str],
) -> List[CommandResult]:
    """在目标主机上停止 supervisorctl 模块。遇首个失败即停止。"""
    results: List[CommandResult] = []
    for module_name in modules:
        cmd = "sudo supervisorctl stop {}".format(shlex.quote(module_name))
        logger.info("Stopping %s on %s: %s", module_name, soc_label, cmd)
        result = run_remote(
            host=host, port=port, user=user,
            password=ssh_password,
            remote_command=cmd,
            timeout_sec=timeout_sec,
            check=True,
        )
        results.append(result)
        logger.info("Stopped %s on %s", module_name, soc_label)
    return results


def _start_modules(
    host: str, port: int, user: str,
    modules: List[str], timeout_sec: int,
    soc_label: str, ssh_password: Optional[str],
) -> List[CommandResult]:
    """在目标主机上启动 supervisorctl 模块。遇首个失败即停止。"""
    results: List[CommandResult] = []
    for module_name in modules:
        cmd = "sudo supervisorctl start {}".format(shlex.quote(module_name))
        logger.info("Starting %s on %s: %s", module_name, soc_label, cmd)
        result = run_remote(
            host=host, port=port, user=user,
            password=ssh_password,
            remote_command=cmd,
            timeout_sec=timeout_sec,
            check=True,
        )
        results.append(result)
        logger.info("Started %s on %s", module_name, soc_label)
    return results


def switch_to_playback_mode(
    context: RunContext, config: ToolConfig
) -> StepResult:
    """将台架模块切换到回灌就绪状态。

    - soc1 停止: Camera, Canbus
    - soc2 停止: Camera, Driver-GNSS, Driver-LiDAR, Driver-NTRIP
    - soc2 启动: Debug_Camera-Decode, Debug_Driver-LiDAR

    任一 SSH 或 supervisorctl 错误时立即失败（fail-fast）。
    MVP 不自动回滚部分失败的模块状态。
    """
    started_at = datetime.now(timezone.utc)
    commands: List[CommandResult] = []
    soc1_stopped: List[str] = []
    soc2_stopped: List[str] = []
    soc2_started: List[str] = []

    try:
        logger.info("Stopping modules on soc1: %s", config.stop_modules_soc1)
        soc1_results = _stop_modules(
            host=config.soc1_host, port=config.soc1_port,
            user=config.soc1_user, modules=config.stop_modules_soc1,
            timeout_sec=config.command_timeout_sec, soc_label="soc1",
            ssh_password=config.ssh_password,
        )
        commands.extend(soc1_results)
        soc1_stopped = list(config.stop_modules_soc1)

        logger.info("Stopping modules on soc2: %s", config.stop_modules_soc2)
        soc2_stop_results = _stop_modules(
            host=config.soc2_host, port=config.soc2_port,
            user=config.soc2_user, modules=config.stop_modules_soc2,
            timeout_sec=config.command_timeout_sec, soc_label="soc2",
            ssh_password=config.ssh_password,
        )
        commands.extend(soc2_stop_results)
        soc2_stopped = list(config.stop_modules_soc2)

        logger.info("Starting debug modules on soc2: %s",
                    config.start_debug_modules_soc2)
        soc2_start_results = _start_modules(
            host=config.soc2_host, port=config.soc2_port,
            user=config.soc2_user, modules=config.start_debug_modules_soc2,
            timeout_sec=config.command_timeout_sec, soc_label="soc2",
            ssh_password=config.ssh_password,
        )
        commands.extend(soc2_start_results)
        soc2_started = list(config.start_debug_modules_soc2)

    except CommandExecutionError as exc:
        ended_at = datetime.now(timezone.utc)
        duration_sec = (ended_at - started_at).total_seconds()
        logger.error("Module switching failed: %s", exc)

        # 诊断: journalctl + 失败模块的 supervisorctl status
        diag: Dict[str, str] = {}
        _failed_module = _extract_failed_module(commands)
        _failed_host = (
            config.soc1_host if soc1_stopped and not soc2_stopped and not soc2_started
            else config.soc2_host
        )
        _failed_port = config.soc1_port if _failed_host == config.soc1_host else config.soc2_port

        for _h, _p, _u, _lbl in [
            (config.soc1_host, config.soc1_port, config.soc1_user, "soc1"),
            (config.soc2_host, config.soc2_port, config.soc2_user, "soc2"),
        ]:
            try:
                _jr = run_remote(
                    host=_h, port=_p, user=_u,
                    password=config.ssh_password,
                    remote_command="journalctl -xeu mdrive.service -n 50 --no-pager || true",
                    timeout_sec=config.command_timeout_sec, check=False,
                )
                diag["journalctl_{}".format(_lbl)] = _jr.stdout.strip()
            except Exception:
                diag["journalctl_{}".format(_lbl)] = "<collection failed>"

        # 额外采集失败模块的 supervisorctl status（best-effort）
        if _failed_module:
            try:
                _sr = run_remote(
                    host=_failed_host, port=_failed_port,
                    user=config.soc1_user if _failed_host == config.soc1_host else config.soc2_user,
                    password=config.ssh_password,
                    remote_command="sudo supervisorctl status {}".format(shlex.quote(_failed_module)),
                    timeout_sec=config.command_timeout_sec, check=False,
                )
                diag["supervisorctl_status_{}".format(_failed_module)] = _sr.stdout.strip()
            except Exception:
                diag["supervisorctl_status_{}".format(_failed_module)] = "<collection failed>"

        return StepResult(
            name="switch_modules", status=StepStatus.FAILED,
            started_at=started_at.isoformat(), ended_at=ended_at.isoformat(),
            duration_sec=duration_sec,
            message="Module switching failed: {}".format(exc),
            commands=commands,
            artifacts={
                "soc1_stopped": soc1_stopped,
                "soc2_stopped": soc2_stopped,
                "soc2_started": soc2_started,
                "diagnostics": diag,
            },
            error_type=type(exc).__name__,
        )

    except Exception as exc:
        ended_at = datetime.now(timezone.utc)
        duration_sec = (ended_at - started_at).total_seconds()
        logger.exception("Unexpected error during module switching")
        return StepResult(
            name="switch_modules", status=StepStatus.FAILED,
            started_at=started_at.isoformat(), ended_at=ended_at.isoformat(),
            duration_sec=duration_sec,
            message="Unexpected error: {}".format(exc),
            commands=commands,
            artifacts={
                "soc1_stopped": soc1_stopped,
                "soc2_stopped": soc2_stopped,
                "soc2_started": soc2_started,
            },
            error_type="UnexpectedError",
        )

    ended_at = datetime.now(timezone.utc)
    duration_sec = (ended_at - started_at).total_seconds()

    return StepResult(
        name="switch_modules", status=StepStatus.SUCCESS,
        started_at=started_at.isoformat(), ended_at=ended_at.isoformat(),
        duration_sec=duration_sec,
        message="Module switching completed",
        commands=commands,
        artifacts={
            "soc1_stopped": soc1_stopped,
            "soc2_stopped": soc2_stopped,
            "soc2_started": soc2_started,
        },
    )
