"""通过 systemctl + vmc install 在 soc1 上执行版本安装与管理。"""

import logging
import re
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


def _parse_vmc_list(raw: str) -> Dict[str, str]:
    """从 vmc list 输出中提取 {package_name: version} 映射。

    vmc list 固定输出格式:
        Installed Software Packages:
        ----------------------------
        <package> (<version>)
        <package> (<version>)
        ...

    仅匹配 "<package> (<version>)" 行，其余行（表头/分隔线）自动跳过。
    """
    installed: Dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        m = re.match(r"^(\S+)\s+\((.+)\)$", line)
        if m:
            installed[m.group(1)] = m.group(2)
    return installed


def _skip_if_installed(pkg_name: str, pkg_version: str, version_info: str) -> bool:
    """检查 (package, version) 对是否已出现在 vmc list 输出中。"""
    installed = _parse_vmc_list(version_info)
    return installed.get(pkg_name) == pkg_version


def install_packages(packages: list, config: ToolConfig) -> StepResult:
    """批次级软件安装：对所有 packages 执行 vmc install，不依赖 RunContext。

    先检查当前版本：若所有包均已安装则直接返回，节省 stop/start 开销。
    否则:
    1. 停止 soc1 / soc2 上的 mdrive（sudo systemctl stop mdrive）
    2. 清理残留的 vmc install 僵尸进程
    3. 在 soc1 上对需要安装的包执行 vmc install -n <pkg> -v <ver> [--deps]
    4. 重新启动 soc1 / soc2 上的 mdrive（sudo systemctl start mdrive）
    """
    started_at = datetime.now(timezone.utc)
    commands: List[CommandResult] = []
    installed_packages: List[Dict[str, str]] = []

    # 1. 捕获当前版本信息，预判哪些包需要安装
    before_info = _collect_raw_version_info(config)

    to_install: list = []
    for pkg in packages:
        if _skip_if_installed(pkg.package, pkg.version, before_info):
            logger.info(
                "SKIP %s=%s — already installed on soc1",
                pkg.package, pkg.version,
            )
            installed_packages.append({
                "package": pkg.package,
                "version": pkg.version,
                "action": "skipped",
            })
        else:
            to_install.append(pkg)

    # 全部已安装 — 无需 stop/install/start
    if not to_install:
        ended_at = datetime.now(timezone.utc)
        duration_sec = (ended_at - started_at).total_seconds()
        logger.info(
            "All %d package(s) already installed; skipping mdrive restart.",
            len(packages),
        )
        return StepResult(
            name="install_versions",
            status=StepStatus.SUCCESS,
            started_at=started_at.isoformat(),
            ended_at=ended_at.isoformat(),
            duration_sec=duration_sec,
            message="All {} package(s) already installed, no service restart needed".format(
                len(packages)
            ),
            commands=commands,
            artifacts={
                "before_version_info": before_info,
                "installed_packages": installed_packages,
            },
        )

    # 2. 至少有一个包需要安装 → 停止 mdrive
    logger.info(
        "%d package(s) need installation; stopping mdrive on soc1/soc2",
        len(to_install),
    )
    for host_label, host, port, user in [
        ("soc1", config.soc1_host, config.soc1_port, config.soc1_user),
        ("soc2", config.soc2_host, config.soc2_port, config.soc2_user),
    ]:
        logger.info("Stopping mdrive on %s", host_label)
        try:
            stop_result = run_remote(
                host=host, port=port, user=user,
                password=config.ssh_password,
                remote_command="sudo systemctl stop mdrive",
                timeout_sec=config.command_timeout_sec,
                check=False,
            )
            commands.append(stop_result)
        except Exception:
            logger.warning("Failed to stop mdrive on %s (non-fatal)", host_label)

    # 3. 清理残留 VMC 进程
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

    try:
        for pkg in to_install:
            install_cmd = (
                env.shell_init()
                + "vmc install -n {} -v {}{}".format(
                    shlex.quote(pkg.package),
                    shlex.quote(pkg.version),
                    " --deps" if pkg.package == "mdrive_map" else "",
                )
            )
            logger.info(
                "INSTALL %s=%s on soc1 (timeout %ds)",
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

        # 4. 启动 soc1 / soc2 上的 mdrive
        for host_label, host, port, user in [
            ("soc1", config.soc1_host, config.soc1_port, config.soc1_user),
            ("soc2", config.soc2_host, config.soc2_port, config.soc2_user),
        ]:
            logger.info("Starting mdrive on %s", host_label)
            start_result = run_remote(
                host=host, port=port, user=user,
                password=config.ssh_password,
                remote_command="sudo systemctl start mdrive",
                timeout_sec=config.command_timeout_sec,
                check=True,
            )
            commands.append(start_result)
            logger.info("mdrive started on %s", host_label)

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
            len(to_install)
        ),
        commands=commands,
        artifacts={
            "before_version_info": before_info,
            "after_version_info": after_info,
            "installed_packages": installed_packages,
        },
    )


def install_versions(context: RunContext, config: ToolConfig) -> StepResult:
    """per-dataset 包装器，委托给批次级 install_packages。
    
    保留此函数以兼容 debug 模式和单点 install_version 调用。
    """
    return install_packages(context.packages, config)
