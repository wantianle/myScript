# -*- coding: utf-8 -*-
"""统一命令执行：本地 subprocess 和远程 SSH。

本模块是唯一允许直接调用 subprocess / ssh 的模块。
密码注入统一在此处理，不在各个调用方分散。
"""

from __future__ import annotations

import os
import socket
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, FrozenSet, List, Optional

from bench_smoke.models import CommandExecutionError, CommandResult


# 环回地址：工具在 soc2 上运行时，目标为 soc2 的命令应直接本地执行，
# 不走 SSH 回连 localhost。
_LOOPBACK_HOSTS: FrozenSet[str] = frozenset({
    "localhost",
    "127.0.0.1",
    "::1",
    "0.0.0.0",
})


def _is_localhost(host: str) -> bool:
    """判断 host 是否为本地机器。"""
    if host.lower() in _LOOPBACK_HOSTS:
        return True
    try:
        if host == socket.gethostname():
            return True
    except Exception:
        pass
    return False


# 内部实现

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class _PopenResult:
    stdout: str
    stderr: str
    return_code: int
    duration_sec: float
    timed_out: bool


def _run_argv(
    argv: List[str],
    timeout_sec: int,
    cwd: Optional[str] = None,
    extra_env: Optional[Dict[str, str]] = None,
    stdin_input: Optional[str] = None,
) -> _PopenResult:
    """通过 subprocess 执行 argv 列表。"""
    started = time.monotonic()

    env = None
    if extra_env:
        env = os.environ.copy()
        env.update(extra_env)

    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            cwd=cwd,
            env=env,
            input=stdin_input,
        )
        ended = time.monotonic()
        return _PopenResult(
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            return_code=proc.returncode,
            duration_sec=ended - started,
            timed_out=False,
        )
    except subprocess.TimeoutExpired as exc:
        ended = time.monotonic()
        return _PopenResult(
            stdout=(exc.stdout or "") if isinstance(exc.stdout, str) else "",
            stderr=(exc.stderr or "") if isinstance(exc.stderr, str) else "",
            return_code=-1,
            duration_sec=ended - started,
            timed_out=True,
        )


def _check_result(
    result: _PopenResult,
    display_command: str,
    check: bool,
) -> None:
    if not check:
        return
    if result.timed_out:
        raise CommandExecutionError(f"Command timed out: {display_command}")
    if result.return_code != 0:
        details: List[str] = []
        if result.stdout.strip():
            details.append(f"stdout: {result.stdout.rstrip()}")
        if result.stderr.strip():
            details.append(f"stderr: {result.stderr.rstrip()}")
        extra = "\n".join(details) if details else "(no output)"
        raise CommandExecutionError(
            f"Command failed (rc={result.return_code}): {display_command}\n{extra}"
        )


def _build_ssh_args(
    host: str, port: int, user: str,
    password: Optional[str], remote_command: str,
) -> List[str]:
    """构建 SSH argv 列表，有密码时通过 sshpass -e 传递。"""
    base = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-p", str(port),
        f"{user}@{host}",
        remote_command,
    ]

    if password:
        if not _sshpass_available():
            raise CommandExecutionError(
                "SSH password configured but sshpass is not available on the PATH. "
                "Install sshpass or use key-based authentication."
            )
        return ["sshpass", "-e"] + base

    return base


_SSHPASS_CHECKED: bool = False
_SSHPASS_FOUND: bool = False


def _sshpass_available() -> bool:
    global _SSHPASS_CHECKED, _SSHPASS_FOUND
    if not _SSHPASS_CHECKED:
        _SSHPASS_FOUND = any(
            os.path.isfile(os.path.join(p, "sshpass"))
            for p in os.environ.get("PATH", "").split(os.pathsep)
        )
        _SSHPASS_CHECKED = True
    return _SSHPASS_FOUND


# 公开接口

def run_local(
    command: List[str],
    timeout_sec: int,
    check: bool = True,
    cwd: Optional[str] = None,
) -> CommandResult:
    """本地执行命令（argv 列表，非 shell 字符串）。"""
    started_at = _now_iso()
    display = " ".join(command)

    result = _run_argv(command, timeout_sec=timeout_sec, cwd=cwd)
    ended_at = _now_iso()

    cr = CommandResult(
        command=list(command),
        display_command=display,
        return_code=result.return_code,
        stdout=result.stdout,
        stderr=result.stderr,
        started_at=started_at,
        ended_at=ended_at,
        duration_sec=result.duration_sec,
        timed_out=result.timed_out,
    )

    _check_result(result, display, check)
    return cr


def run_remote(
    host: str,
    port: int,
    user: str,
    remote_command: str,
    timeout_sec: int,
    check: bool = True,
    password: Optional[str] = None,
) -> CommandResult:
    """通过 SSH 在远程主机上执行命令。

    host 为本地机器时（如 localhost/127.0.0.1），直接本地执行，
    不走 SSH。有密码且命令以 sudo 开头时，通过 stdin 注入密码。
    """
    # 本地目标 → 直接本地执行
    if _is_localhost(host):
        started_at = _now_iso()
        display = f"[local] {remote_command}"

        local_command = remote_command
        sudo_stdin: Optional[str] = None
        if password is not None and remote_command.lstrip().startswith("sudo"):
            idx = remote_command.find("sudo")
            local_command = (
                remote_command[: idx + 4] + " -S" + remote_command[idx + 4 :]
            )
            sudo_stdin = password + "\n"

        result = _run_argv(
            ["bash", "-c", local_command],
            timeout_sec=timeout_sec,
            stdin_input=sudo_stdin,
        )
        ended_at = _now_iso()
        cr = CommandResult(
            command=["bash", "-c", local_command],
            display_command=display,
            return_code=result.return_code,
            stdout=result.stdout,
            stderr=result.stderr,
            started_at=started_at,
            ended_at=ended_at,
            duration_sec=result.duration_sec,
            timed_out=result.timed_out,
        )
        _check_result(result, display, check)
        return cr

    # 远程执行 → SSH
    started_at = _now_iso()
    display = f"ssh -p {port} {user}@{host} \"{remote_command}\""

    extra_env: Dict[str, str] = {}
    if password:
        extra_env["SSHPASS"] = password

    argv = _build_ssh_args(host, port, user, password, remote_command)
    result = _run_argv(argv, timeout_sec=timeout_sec, extra_env=extra_env)
    ended_at = _now_iso()

    safe_command: List[str] = [
        "***" if a == password else a for a in argv
    ]

    cr = CommandResult(
        command=safe_command,
        display_command=display,
        return_code=result.return_code,
        stdout=result.stdout,
        stderr=result.stderr,
        started_at=started_at,
        ended_at=ended_at,
        duration_sec=result.duration_sec,
        timed_out=result.timed_out,
    )

    _check_result(result, display, check)
    return cr
