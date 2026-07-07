# -*- coding: utf-8 -*-
"""共享数据类型。

所有 dataclass、enum 和自定义异常均在此定义。本模块不得包含
shell 执行或文件系统副作用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# 自定义异常

class BenchSmokeError(Exception):
    """bench_smoke 基础异常。"""


class ConfigError(BenchSmokeError):
    """配置无效或缺失时抛出。"""


class ManifestError(BenchSmokeError):
    """清单加载或校验失败时抛出。"""


class CommandExecutionError(BenchSmokeError):
    """命令执行失败（非零返回码、超时等）时抛出。"""


# 步骤状态

class StepStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


# 数据集与包类型

@dataclass
class DatasetEntry:
    dataset_id: str
    issue_description: str
    feishu_url: str
    source_path: str
    short_name: str = ""
    tags: List[str] = field(default_factory=list)


@dataclass
class PackageSpec:
    package: str
    version: str
    install_with_deps: bool = True


# 工具配置

@dataclass
class ToolConfig:
    # -- 路径 --
    run_root: str = "/mdrive_data/bench_smoke_runs"
    record_root: str = "/mdrive_data/bag"
    mount_check_path: str = "/media/nas"

    # -- soc 连接 --
    soc1_host: str = "192.168.10.2"
    soc1_user: str = "nvidia"
    soc1_port: int = 22

    soc2_host: str = "192.168.10.3"
    soc2_user: str = "nvidia"
    soc2_port: int = 22

    # -- SSH 认证（统一入口） --
    ssh_password: Optional[str] = None

    # -- 模块控制 --
    stop_modules_soc1: List[str] = field(default_factory=lambda: [
        "Camera",
        "Canbus",
    ])
    stop_modules_soc2: List[str] = field(default_factory=lambda: [
        "Camera",
        "Driver-GNSS",
        "Driver-LiDAR",
        "Driver-NTRIP",
    ])
    start_debug_modules_soc2: List[str] = field(default_factory=lambda: [
        "Debug_Camera-Decode",
        "Debug_Driver-LiDAR",
    ])

    # -- 回灌 --
    playback_topics: List[str] = field(default_factory=lambda: [
        "/sensor/gnss/raw",
        "/sensor/gnss",
        "/sensor/gnss/gpgga",
        "/sensor/cors/rtcm",
        "/sensor/ins",
        "/sensor/imu",
        "/sensor/imu/calib_state",
        "/sensor/lidar/scan",
        "camera1",
        "camera4",
        "camera2",
        "camera3",
        "camera5",
        "camera6",
        "camera7",
        "camera81",
        "camera82",
        "camera83",
        "camera84",
        "/vehicle/highfreq",
        "/vehicle/lowfreq",
    ])

    # -- 超时（秒） --
    command_timeout_sec: int = 30
    install_timeout_sec: int = 600
    rsync_timeout_sec: int = 900
    playback_timeout_sec: int = 60
    recorder_start_timeout_sec: int = 30
    recorder_stop_timeout_sec: int = 30

    # -- 录制提前停止偏移量（秒） --
    # 回灌与录制重叠时，在回灌预计结束前提前停止录制，
    # 避免产生多余的尾部 mcap 片段。
    recorder_early_stop_offset_sec: float = 0.5


# 命令执行结果

@dataclass
class CommandResult:
    command: List[str]
    display_command: str
    return_code: int
    stdout: str
    stderr: str
    started_at: str
    ended_at: str
    duration_sec: float
    timed_out: bool = False


# 步骤执行结果

@dataclass
class StepResult:
    name: str
    status: StepStatus
    started_at: str
    ended_at: str
    duration_sec: float
    message: str
    commands: List[CommandResult] = field(default_factory=list)
    artifacts: Dict[str, Any] = field(default_factory=dict)
    error_type: Optional[str] = None
    log_path: Optional[str] = None


# 运行上下文与汇总

@dataclass
class RunContext:
    run_id: str
    run_dir: str
    dataset: DatasetEntry
    packages: List[PackageSpec]
    batch_timestamp: str = ""
    local_dataset_path: Optional[str] = None
    record_output_dir: Optional[str] = None
    generated_mcaps: List[str] = field(default_factory=list)


@dataclass
class RunSummary:
    run_id: str
    dataset_id: str
    issue_description: str
    feishu_url: str
    status: StepStatus
    failed_step: Optional[str]
    packages: List[PackageSpec]
    source_path: str
    local_dataset_path: Optional[str]
    record_output_dir: Optional[str]
    generated_mcaps: List[str]
    step_results: List[StepResult]
    summary_path: str


# 版本快照

@dataclass
class VersionSnapshot:
    version_info_raw: str
    captured_at: str
