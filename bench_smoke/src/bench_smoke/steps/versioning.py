"""通过 md-tool 在 soc1 上执行版本安装与检查。"""

import logging
import shlex
from datetime import datetime, timezone
from typing import Dict, List

from .. import env
from ..command_runner import CommandExecutionError, run_remote
from ..config import ToolConfig
from ..models import CommandResult, RunContext, StepResult, StepStatus, VersionSnapshot

logger = logging.getLogger(__name__)


def _collect_raw_version_info(config: ToolConfig) -> str:
    """从 soc1 捕获当前已安装版本信息原始文本。"""
    try:
        result = run_remote(
            host=config.soc1_host,
            port=config.soc1_port,
            user=config.soc1_user,
            password=config.ssh_password,
            remote_command=env.shell_init() + "(vmc list || true)",
            timeout_sec=config.command_timeout_sec,
            check=False,
        )
        return result.stdout.strip()
    except Exception:
        logger.exception("Failed to inspect versions on soc1")
        return ""


def inspect_versions(config: ToolConfig) -> VersionSnapshot:
    """捕获 soc1 上的当前版本信息（信息性追踪，容忍失败）。"""
    return VersionSnapshot(
        version_info_raw=_collect_raw_version_info(config),
        captured_at=datetime.now(timezone.utc).isoformat(),
    )


def _skip_if_installed(pkg_version: str, version_info: str) -> bool:
    """检查 pkg_version 是否出现在 version_info 字符串中。"""
    return pkg_version in version_info


def install_versions(context: RunContext, config: ToolConfig) -> StepResult:
    """在 soc1 上安装目标软件版本并启动 mdrive 服务。

    依次执行:
    1. 清理残留的 vmc install 僵尸进程
    2. 捕获当前已安装版本信息
    3. 对每个 package spec：若目标版本已安装则跳过，否则执行 md install
    4. 启动 mdrive 服务

    md install 通过 SSH 在 soc1 上执行，下载耗时取决于 bench 网络速度。
    若 subprocess 输出被完全捕获，进度条不会实时显示——下载期间无新日志。
    """
    started_at = datetime.now(timezone.utc)
    commands: List[CommandResult] = []
    installed_packages: List[Dict[str, str]] = []

    # 1. 清理残留 VMC 进程
    try:
        run_remote(
            host=config.soc1_host,
            port=config.soc1_port,
            user=config.soc1_user,
            password=config.ssh_password,
            remote_command="pkill -f 'vmc install' 2>/dev/null; echo done",
            timeout_sec=config.command_timeout_sec,
            check=False,
        )
    except Exception:
        pass

    # 2. 捕获安装前版本信息
    before_info = _collect_raw_version_info(config)

    try:
        for pkg in context.packages:
            # 跳过已安装的版本（对比 vmc list 输出）
            if _skip_if_installed(pkg.version, before_info):
                logger.info(
                    "SKIP %s=%s — already installed on soc1",
                    pkg.package, pkg.version,
                )
                installed_packages.append({
                    "package": pkg.package,
                    "version": pkg.version,
                    "action": "skipped",
                })
                continue

            install_cmd = env.shell_init() + "md install {}".format(shlex.quote(pkg.version))
            logger.info(
                "INSTALL %s=%s on soc1 (timeout %ds). "
                "md install may download ~100 MB; subprocess output is captured "
                "so no progress lines appear until it finishes.",
                pkg.package, pkg.version, config.install_timeout_sec,
            )
            t0 = datetime.now(timezone.utc)

            result = run_remote(
                host=config.soc1_host,
                port=config.soc1_port,
                user=config.soc1_user,
                password=config.ssh_password,
                remote_command=install_cmd,
                timeout_sec=config.install_timeout_sec,
                check=True,
            )
            elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
            commands.append(result)
            installed_packages.append({
                "package": pkg.package,
                "version": pkg.version,
                "action": "installed",
            })
            logger.info("DONE %s=%s (%.1fs)", pkg.package, pkg.version, elapsed)

        # 3. 启动 mdrive 服务
        logger.info("Starting mdrive service on soc1 (md start)")
        start_result = run_remote(
            host=config.soc1_host,
            port=config.soc1_port,
            user=config.soc1_user,
            password=config.ssh_password,
            remote_command=env.shell_init() + "md start",
            timeout_sec=config.command_timeout_sec,
            check=True,
        )
        commands.append(start_result)
        logger.info("mdrive service started successfully")

    except CommandExecutionError as exc:
        ended_at = datetime.now(timezone.utc)
        duration_sec = (ended_at - started_at).total_seconds()
        logger.error("Version installation failed: %s", exc)
        return StepResult(
            name="install_versions",
            status=StepStatus.FAILED,
            started_at=started_at.isoformat(),
            ended_at=ended_at.isoformat(),
            duration_sec=duration_sec,
            message="Version installation failed: {}".format(exc),
            commands=commands,
            artifacts={
                "before_version_info": before_info,
                "installed_packages": installed_packages,
            },
            error_type=type(exc).__name__,
        )

    except Exception as exc:
        ended_at = datetime.now(timezone.utc)
        duration_sec = (ended_at - started_at).total_seconds()
        logger.exception("Unexpected error during version installation")
        return StepResult(
            name="install_versions",
            status=StepStatus.FAILED,
            started_at=started_at.isoformat(),
            ended_at=ended_at.isoformat(),
            duration_sec=duration_sec,
            message="Unexpected error: {}".format(exc),
            commands=commands,
            artifacts={
                "before_version_info": before_info,
                "installed_packages": installed_packages,
            },
            error_type="UnexpectedError",
        )

    after_info = _collect_raw_version_info(config)
    ended_at = datetime.now(timezone.utc)
    duration_sec = (ended_at - started_at).total_seconds()

    return StepResult(
        name="install_versions",
        status=StepStatus.SUCCESS,
        started_at=started_at.isoformat(),
        ended_at=ended_at.isoformat(),
        duration_sec=duration_sec,
        message="Installed {} package(s) and started mdrive".format(
            len(installed_packages)
        ),
        commands=commands,
        artifacts={
            "before_version_info": before_info,
            "after_version_info": after_info,
            "installed_packages": installed_packages,
        },
    )
