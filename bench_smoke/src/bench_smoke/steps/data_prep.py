"""数据准备：从 NAS 将原始传感器数据复制到本地缓存目录。

实现稳定缓存：按 dataset_id 缓存，用 source_manifest.txt 检测
source_path 变化，不一致则删除重拷。
"""

import logging
import os
import shutil
from datetime import datetime, timezone
from typing import List, Optional

from ..command_runner import CommandExecutionError, run_local
from ..config import ToolConfig
from ..models import CommandResult, RunContext, StepResult, StepStatus

logger = logging.getLogger(__name__)

# 缓存目录中记录源路径的哨兵文件名
_CACHE_SENTINEL = "source_manifest.txt"


def _build_cache_path(context: RunContext, config: ToolConfig) -> str:
    """根据 dataset_id 生成稳定的缓存路径（不含 hash 后缀）。

    路径格式:
        {run_root}/cache/{dataset_id}/
    """
    return os.path.join(config.run_root, "cache", context.dataset.dataset_id)


def _read_cached_source(cache_dir: str) -> Optional[str]:
    """读取缓存哨兵，返回缓存的源路径；无有效哨兵时返回 None。"""
    sentinel_path = os.path.join(cache_dir, _CACHE_SENTINEL)
    if not os.path.isfile(sentinel_path):
        return None
    try:
        with open(sentinel_path, "r", encoding="utf-8") as fh:
            return fh.readline().strip()
    except Exception:
        logger.warning("Could not read cache sentinel %s", sentinel_path)
        return None


def _write_cache_sentinel(cache_dir: str, source_path: str) -> None:
    sentinel_path = os.path.join(cache_dir, _CACHE_SENTINEL)
    with open(sentinel_path, "w", encoding="utf-8") as fh:
        fh.write(source_path + "\n")


def prepare_dataset(context: RunContext, config: ToolConfig) -> StepResult:
    """将原始传感器数据从清单源路径复制到稳定缓存目录。

    缓存命中时跳过复制，直接复用已有本地数据。

    步骤:
    1. 验证挂载点。
    2. 校验源路径（文件或目录）。
    3. 生成缓存路径；如命中则标记复用。
    4. 未命中时从源复制数据并写入哨兵文件。
    5. 验证缓存非空。
    """
    started_at = datetime.now(timezone.utc)
    commands: List[CommandResult] = []

    source_path = context.dataset.source_path
    cache_dir = _build_cache_path(context, config)
    data_dir = os.path.join(cache_dir, "data")

    try:
        # 1. 验证挂载点
        mount_check_path = config.mount_check_path or "/media/nas"
        logger.info("Verifying mount point: %s", mount_check_path)
        mount_result = run_local(
            command=["mountpoint", "-q", mount_check_path],
            timeout_sec=config.command_timeout_sec,
            check=False,
        )
        commands.append(mount_result)
        if mount_result.return_code != 0:
            raise RuntimeError(
                "Mount point {} is not mounted or not accessible".format(
                    mount_check_path
                )
            )

        # 2. 校验源路径
        logger.info("Validating source path: %s", source_path)
        if not source_path:
            raise RuntimeError("Source path is empty")
        if not os.path.exists(source_path):
            raise RuntimeError("Source path does not exist: {}".format(source_path))

        # 3. 缓存命中检查
        cached_source = _read_cached_source(cache_dir)
        if cached_source == source_path:
            logger.info("Cache HIT — reusing localised data at %s", data_dir)
            context.local_dataset_path = data_dir
            ended_at = datetime.now(timezone.utc)
            duration_sec = (ended_at - started_at).total_seconds()
            return StepResult(
                name="prepare_data",
                status=StepStatus.SUCCESS,
                started_at=started_at.isoformat(),
                ended_at=ended_at.isoformat(),
                duration_sec=duration_sec,
                message="Data reused from cache at {}".format(data_dir),
                commands=commands,
                artifacts={
                    "source_path": source_path,
                    "local_dataset_path": data_dir,
                    "cache_hit": True,
                    "copy_return_code": 0,
                },
            )

        if cached_source and cached_source != source_path:
            logger.warning(
                "Cache dir %s has stale sentinel (%s vs %s); removing and recopying",
                cache_dir, cached_source, source_path,
            )
            shutil.rmtree(cache_dir, ignore_errors=True)

        # 4. 缓存未命中 — 复制数据
        source_is_file = os.path.isfile(source_path)
        logger.info("Cache MISS — copying to %s", data_dir)
        os.makedirs(data_dir, exist_ok=True)

        _use_rsync = shutil.which("rsync") is not None
        copy_start = datetime.now(timezone.utc)

        if _use_rsync:
            if source_is_file:
                copy_cmd = [
                    "rsync", "-a", "--info=progress2",
                    source_path,
                    data_dir.rstrip("/") + "/",
                ]
            else:
                rsync_source = source_path.rstrip("/") + "/"
                rsync_dest = data_dir.rstrip("/") + "/"
                copy_cmd = [
                    "rsync", "-a", "--info=progress2",
                    rsync_source, rsync_dest,
                ]

            logger.info("Rsync: %s -> %s", source_path, data_dir)
            copy_result = run_local(
                command=copy_cmd,
                timeout_sec=config.rsync_timeout_sec,
                check=True,
            )
        else:
            logger.info(
                "rsync not available; copying via Python stdlib: %s -> %s",
                source_path, data_dir,
            )
            if source_is_file:
                shutil.copy2(source_path, data_dir.rstrip("/") + "/")
            else:
                for item in os.listdir(source_path):
                    src_item = os.path.join(source_path, item)
                    dst_item = os.path.join(data_dir, item)
                    if os.path.isdir(src_item):
                        shutil.copytree(src_item, dst_item)
                    else:
                        shutil.copy2(src_item, dst_item)

            copy_end = datetime.now(timezone.utc)
            copy_result = CommandResult(
                command=["python", "shutil"],
                display_command="[stdlib] copy {} -> {}".format(
                    source_path, data_dir
                ),
                return_code=0,
                stdout="",
                stderr="",
                started_at=copy_start.isoformat(),
                ended_at=copy_end.isoformat(),
                duration_sec=(copy_end - copy_start).total_seconds(),
                timed_out=False,
            )

        commands.append(copy_result)
        logger.info(
            "Copy completed (method=%s, rc=%d, elapsed=%.1fs)",
            "rsync" if _use_rsync else "stdlib",
            copy_result.return_code,
            copy_result.duration_sec,
        )

        _write_cache_sentinel(cache_dir, source_path)

        # 5. 验证非空
        if not os.path.isdir(data_dir) or not os.listdir(data_dir):
            raise RuntimeError(
                "Data directory is empty after copy: {}".format(data_dir)
            )

    except CommandExecutionError as exc:
        ended_at = datetime.now(timezone.utc)
        duration_sec = (ended_at - started_at).total_seconds()
        logger.error("Data preparation failed: %s", exc)
        return StepResult(
            name="prepare_data",
            status=StepStatus.FAILED,
            started_at=started_at.isoformat(),
            ended_at=ended_at.isoformat(),
            duration_sec=duration_sec,
            message="Data preparation failed: {}".format(exc),
            commands=commands,
            artifacts={
                "source_path": source_path,
                "local_dataset_path": data_dir,
                "cache_hit": False,
            },
            error_type=type(exc).__name__,
        )

    except RuntimeError as exc:
        ended_at = datetime.now(timezone.utc)
        duration_sec = (ended_at - started_at).total_seconds()
        logger.error("Data preparation guard failed: %s", exc)
        return StepResult(
            name="prepare_data",
            status=StepStatus.FAILED,
            started_at=started_at.isoformat(),
            ended_at=ended_at.isoformat(),
            duration_sec=duration_sec,
            message="Data preparation failed: {}".format(exc),
            commands=commands,
            artifacts={
                "source_path": source_path,
                "local_dataset_path": data_dir,
                "cache_hit": False,
            },
            error_type="GuardFailure",
        )

    except Exception as exc:
        ended_at = datetime.now(timezone.utc)
        duration_sec = (ended_at - started_at).total_seconds()
        logger.exception("Unexpected error during data preparation")
        return StepResult(
            name="prepare_data",
            status=StepStatus.FAILED,
            started_at=started_at.isoformat(),
            ended_at=ended_at.isoformat(),
            duration_sec=duration_sec,
            message="Unexpected error: {}".format(exc),
            commands=commands,
            artifacts={
                "source_path": source_path,
                "local_dataset_path": data_dir,
                "cache_hit": False,
            },
            error_type="UnexpectedError",
        )

    context.local_dataset_path = data_dir
    ended_at = datetime.now(timezone.utc)
    duration_sec = (ended_at - started_at).total_seconds()

    return StepResult(
        name="prepare_data",
        status=StepStatus.SUCCESS,
        started_at=started_at.isoformat(),
        ended_at=ended_at.isoformat(),
        duration_sec=duration_sec,
        message="Data prepared at {}".format(data_dir),
        commands=commands,
        artifacts={
            "source_path": source_path,
            "local_dataset_path": data_dir,
            "cache_hit": False,
            "copy_return_code": copy_result.return_code,
        },
    )
