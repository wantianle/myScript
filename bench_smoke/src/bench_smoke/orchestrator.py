# -*- coding: utf-8 -*-
"""工作流编排器。

管理高层步骤顺序、fail-fast 策略、recorder 清理策略和 debug 分发。
唯一有权决定"下一个跑什么步骤"的模块。
"""

from __future__ import annotations

import logging
import os
from functools import partial
from typing import Callable, Dict, List, Optional

from bench_smoke.models import (
    DatasetEntry, PackageSpec, RunContext, RunSummary,
    StepResult, StepStatus, ToolConfig,
)
import bench_smoke.result_store as result_store
import bench_smoke.step_runner as step_runner
from bench_smoke.logging_setup import setup_logging

from bench_smoke.steps import versioning
from bench_smoke.steps import data_prep
from bench_smoke.steps import module_control
from bench_smoke.steps import playback
from bench_smoke.steps import recorder
from bench_smoke.steps import metadata

logger = logging.getLogger("bench_smoke.orchestrator")

_StepFn = Callable[[RunContext], StepResult]


def run_full(
    dataset: DatasetEntry,
    packages: List[PackageSpec],
    config: ToolConfig,
    batch_timestamp: Optional[str] = None,
) -> RunSummary:
    """对单个数据集执行录制 + 回灌流程（不含 install_versions / switch_modules，这两步在批次级完成）。

    步骤顺序:
      1. prepare_data
      2. start_recorder
      3. playback（后台启动，紧跟 recorder 之后）
      4. stop_recorder（等待回灌完成后停止录制）
      5. collect_metadata
      6. summarize（内联，写入 RunSummary）

    默认 fail-fast：第一个 FAILED 步骤即停止。
    start_recorder 成功后若后续步骤失败，尝试 best-effort 清理。
    """
    context = result_store.create_run_context(
        dataset, packages, config, batch_timestamp=batch_timestamp,
    )
    setup_logging(context.run_dir, console=True)

    steps: List[tuple] = [
        ("prepare_data",     partial(data_prep.prepare_dataset, config=config)),
        ("start_recorder",   partial(recorder.start_recorder, config=config)),
        ("playback",         partial(playback.play_once, config=config)),
        ("stop_recorder",    partial(recorder.stop_recorder, config=config)),
        ("collect_metadata", partial(metadata.collect_metadata, config=config)),
    ]

    step_results: List[StepResult] = []
    recorder_started = False
    failed_step: Optional[str] = None

    global _playback_proc
    _playback_proc = None

    for step_name, step_fn in steps:
        # -- playback: 后台启动，立即进入 stop_recorder --
        if step_name == "playback":
            result = _launch_playback_background(context, config, step_results)
            if result.status != StepStatus.SUCCESS:
                failed_step = step_name
                break
            continue

        # -- stop_recorder: 等待回灌完成后再停止录制 --
        if step_name == "stop_recorder":
            if not recorder_started:
                continue

            if _playback_proc is not None:
                _wait = _wait_background_playback(
                    _playback_proc, context, config, step_results,
                )
                if _wait.status != StepStatus.SUCCESS:
                    failed_step = "playback"
                    break

            result = step_runner.run_step(step_name, context, step_fn)
            step_results.append(result)
            if result.status != StepStatus.SUCCESS:
                failed_step = step_name
                break
            continue

        # -- 其他步骤: fail-fast --
        result = step_runner.run_step(step_name, context, step_fn)
        step_results.append(result)

        if result.status != StepStatus.SUCCESS:
            failed_step = step_name
            if recorder_started and step_name != "stop_recorder":
                logger.warning(
                    "Step '%s' failed after recorder was started; "
                    "attempting recorder cleanup...", step_name,
                )
                if _playback_proc is not None:
                    _terminate_playback(_playback_proc)
                _cleanup_stop_recorder(context, config, step_results)
            break

        if step_name == "start_recorder":
            recorder_started = True

    return _build_and_write_summary(
        context=context, dataset=dataset, packages=packages,
        step_results=step_results, failed_step=failed_step, config=config,
    )


def run_batch(
    datasets: List[DatasetEntry],
    packages: List[PackageSpec],
    config: ToolConfig,
) -> List[RunSummary]:
    """统一批处理入口：1 条或 N 条数据集使用同一流程。

    1. 创建批次目录（YYYYMMDD_HHMM）
    2. 批次级: install_packages（仅一次）
    3. 批次级: switch_to_playback_mode（仅一次）
    4. 逐条 dataset: prepare_data → recorder/playback → metadata → summarize
    5. 写 batch_summary.txt/json
    6. 上传批次目录到 NAS

    任一批次级步骤失败即整批终止，写入 batch_summary 后返回。
    遇首个 dataset 失败即停止，但仍会写入 batch_summary 和触发 NAS 上传。
    """
    from datetime import datetime as _dt_mod
    import os as _os_mod
    batch_ts = _dt_mod.now().strftime("%Y%m%d_%H%M")
    # 先解析批次目录并创建，避免每个 create_run_context 各自碰撞
    batch_dir, resolved_ts = result_store._resolve_batch_dir(
        config.run_root, batch_ts,
    )
    _os_mod.makedirs(batch_dir, exist_ok=True)

    # 批次级版本安装（仅一次）
    logger.info("Batch-level install: %d package(s)", len(packages))
    install_result = versioning.install_packages(packages, config)
    if install_result.status != StepStatus.SUCCESS:
        logger.error("Batch install failed: %s — aborting entire batch", install_result.message)
        _write_batch_summary(batch_dir, [], install_result=install_result)
        _upload_batch_to_nas(config, batch_dir, [install_result])
        return []

    # 批次级模块切换（仅一次）
    logger.info("Batch-level module switch")
    _setup_ctx = RunContext(
        run_id="batch_setup", run_dir=batch_dir,
        dataset=datasets[0], packages=list(packages),
    )
    try:
        module_switch_result = module_control.switch_to_playback_mode(_setup_ctx, config)
    except Exception as exc:
        from bench_smoke.models import StepResult as _SR
        module_switch_result = _SR(
            name="switch_modules", status=StepStatus.FAILED,
            started_at="", ended_at="", duration_sec=0.0,
            message="Exception during module switch: {}".format(exc),
            error_type="UnexpectedError",
        )
    if module_switch_result.status != StepStatus.SUCCESS:
        logger.error("Batch module switch failed: %s — aborting entire batch",
                     module_switch_result.message)
        _write_batch_summary(
            batch_dir, [], install_result=install_result,
            module_switch_result=module_switch_result,
        )
        _upload_batch_to_nas(
            config, batch_dir, [install_result, module_switch_result],
        )
        return []

    summaries: List[RunSummary] = []
    for dataset in datasets:
        logger.info("Starting batch dataset: %s", dataset.dataset_id)
        summary = run_full(
            dataset, packages, config, batch_timestamp=resolved_ts,
        )
        summaries.append(summary)

        # 单条失败时仍写入 batch_summary 后再停止
        if summary.status == StepStatus.FAILED:
            logger.warning(
                "Dataset %s failed at step '%s'; stopping batch.",
                dataset.dataset_id, summary.failed_step,
            )
            _write_batch_summary(batch_dir, summaries, install_result=install_result,
                                 module_switch_result=module_switch_result)
            break

    if summaries:
        _write_batch_summary(batch_dir, summaries, install_result=install_result,
                             module_switch_result=module_switch_result)

    # 将本次批次目录上传到 NAS
    _upload_batch_to_nas(config, batch_dir, summaries)
    return summaries


# Debug 单步模式

_VALID_DEBUG_STEPS = frozenset({
    "validate_manifest",
    "inspect_version",
    "install_version",
    "prepare_data",
    "switch_modules",
    "start_recorder",
    "playback",
    "stop_recorder",
    "collect_metadata",
    "summarize",
})


def run_debug_step(
    step: str, dataset: DatasetEntry, packages: List[PackageSpec],
    config: ToolConfig, run_id: Optional[str] = None,
) -> StepResult:
    """在隔离模式下执行单个命名步骤（排障模式）。

    debug 模式始终保留 execution.json，即使步骤成功。
    """
    if step not in _VALID_DEBUG_STEPS:
        raise ValueError(
            f"Unknown debug step: '{step}'. "
            f"Valid steps: {', '.join(sorted(_VALID_DEBUG_STEPS))}"
        )

    if run_id is not None:
        context = _load_existing_context(run_id, dataset, packages, config)
    else:
        context = result_store.create_run_context(dataset, packages, config)

    setup_logging(context.run_dir, console=True)
    _check_debug_preconditions(step, context, config)

    result = _dispatch_debug_step(step, context, config)

    # debug 模式：始终将步骤明细写入 execution.json
    _persist_debug_result(context, result)

    return result


def _persist_debug_result(context: RunContext, result: StepResult) -> None:
    """将 debug 步骤结果追加到 execution.json。"""
    try:
        existing = result_store.load_step_results(context)
        existing.append(result)
        result_store.write_execution_json(context, existing)
    except Exception as exc:
        logger.warning("Failed to persist debug execution.json: %s", exc)


def _load_existing_context(
    run_id: str, dataset: DatasetEntry,
    packages: List[PackageSpec], config: ToolConfig,
) -> RunContext:
    import os
    for root, _dirs, files in os.walk(config.run_root):
        if "run_context.json" in files:
            run_dir = os.path.dirname(os.path.join(root, "run_context.json"))
            if run_id in run_dir:
                try:
                    raw = result_store._read_json(os.path.join(run_dir, "run_context.json"))
                    return RunContext(
                        run_id=raw.get("run_id", run_id),
                        run_dir=run_dir, dataset=dataset,
                        packages=list(packages),
                        local_dataset_path=raw.get("local_dataset_path"),
                        record_output_dir=raw.get("record_output_dir"),
                        generated_mcaps=list(raw.get("generated_mcaps", [])),
                    )
                except Exception as exc:
                    raise ValueError(
                        f"Failed to load context for run_id='{run_id}' at {run_dir}: {exc}"
                    ) from exc
    raise ValueError(
        f"No existing run found for run_id='{run_id}'. "
        f"Omit --run-id to create a new run context."
    )


def _check_debug_preconditions(step: str, context: RunContext, config: ToolConfig) -> None:
    if step == "prepare_data":
        if not context.dataset or not context.dataset.source_path:
            raise ValueError("Cannot run 'prepare_data': dataset or source_path is missing.")
    if step == "switch_modules":
        if not config.stop_modules_soc1 and not config.stop_modules_soc2:
            raise ValueError("Cannot run 'switch_modules': module lists are empty in config.")
    if step == "playback":
        if not context.local_dataset_path:
            raise ValueError("Cannot run 'playback': local_dataset_path is not set.")
    if step in ("stop_recorder", "collect_metadata"):
        if not context.record_output_dir:
            raise ValueError(f"Cannot run '{step}': record_output_dir is not set.")


def _dispatch_debug_step(step: str, context: RunContext, config: ToolConfig) -> StepResult:
    from datetime import datetime, timezone

    if step == "validate_manifest":
        started = datetime.now(timezone.utc).isoformat()
        return StepResult(
            name=step, status=StepStatus.SUCCESS,
            started_at=started, ended_at=started, duration_sec=0.0,
            message="Manifest validation passed.",
            artifacts={"dataset_id": context.dataset.dataset_id,
                        "source_path": context.dataset.source_path},
        )
    if step == "inspect_version":
        started_at = datetime.now(timezone.utc).isoformat()
        try:
            snapshot = versioning.inspect_versions(config)
            return StepResult(
                name=step, status=StepStatus.SUCCESS,
                started_at=started_at, ended_at=datetime.now(timezone.utc).isoformat(),
                duration_sec=0.0, message="Version inspection completed.",
                artifacts={"version_info_raw": snapshot.version_info_raw,
                            "captured_at": snapshot.captured_at},
            )
        except Exception as exc:
            return StepResult(name=step, status=StepStatus.FAILED,
                              started_at=started_at, ended_at=datetime.now(timezone.utc).isoformat(),
                              duration_sec=0.0, message=str(exc),
                              error_type=type(exc).__name__)
    if step == "summarize":
        started_at = datetime.now(timezone.utc).isoformat()
        try:
            existing_results = result_store.load_step_results(context)
            any_failed = any(r.status == StepStatus.FAILED for r in existing_results)
            overall = StepStatus.FAILED if any_failed else StepStatus.SUCCESS
            failed_step_name = None
            for r in existing_results:
                if r.status == StepStatus.FAILED:
                    failed_step_name = r.name
                    break
            summary = RunSummary(
                run_id=context.run_id, dataset_id=context.dataset.dataset_id,
                issue_description=context.dataset.issue_description,
                feishu_url=context.dataset.feishu_url,
                status=overall, failed_step=failed_step_name,
                packages=list(context.packages),
                source_path=context.dataset.source_path,
                local_dataset_path=context.local_dataset_path,
                record_output_dir=context.record_output_dir,
                generated_mcaps=list(context.generated_mcaps),
                step_results=existing_results, summary_path=context.run_dir,
            )
            result_store.write_summary(summary)
            return StepResult(name=step, status=StepStatus.SUCCESS,
                              started_at=started_at, ended_at=datetime.now(timezone.utc).isoformat(),
                              duration_sec=0.0, message=f"Summary written to {context.run_dir}",
                              artifacts={"summary_path": context.run_dir})
        except Exception as exc:
            return StepResult(name=step, status=StepStatus.FAILED,
                              started_at=started_at, ended_at=datetime.now(timezone.utc).isoformat(),
                              duration_sec=0.0, message=str(exc), error_type=type(exc).__name__)

    _step_fn_map: Dict[str, _StepFn] = {
        "install_version":  partial(versioning.install_versions, config=config),
        "prepare_data":     partial(data_prep.prepare_dataset, config=config),
        "switch_modules":   partial(module_control.switch_to_playback_mode, config=config),
        "start_recorder":   partial(recorder.start_recorder, config=config),
        "playback":         partial(playback.play_once, config=config),
        "stop_recorder":    partial(recorder.stop_recorder, config=config),
        "collect_metadata": partial(metadata.collect_metadata, config=config),
    }
    fn = _step_fn_map.get(step)
    if fn is None:
        raise ValueError(f"No dispatch handler for debug step: '{step}'")
    return step_runner.run_step(step, context, fn)


# 后台回灌辅助函数（与录制重叠）

def _launch_playback_background(
    context: RunContext, config: ToolConfig, step_results: List[StepResult],
) -> StepResult:
    """以子进程方式后台启动 mkit play，返回合成 StepResult。"""
    import subprocess
    from datetime import datetime as _dt, timezone as _tz

    started_at = _dt.now(_tz.utc).isoformat()
    try:
        cmd, cwd = playback.build_playback_command(context, config)
    except RuntimeError as exc:
        return StepResult(
            name="playback", status=StepStatus.FAILED,
            started_at=started_at, ended_at=_dt.now(_tz.utc).isoformat(),
            duration_sec=0.0, message="Playback guard failed: {}".format(exc),
            error_type="GuardFailure",
        )

    logger.info("Launching playback in background: %s", " ".join(cmd))
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, cwd=cwd,
        )
    except Exception as exc:
        return StepResult(
            name="playback", status=StepStatus.FAILED,
            started_at=started_at, ended_at=_dt.now(_tz.utc).isoformat(),
            duration_sec=0.0,
            message="Failed to launch playback process: {}".format(exc),
            error_type="ProcessError",
        )

    global _playback_proc
    _playback_proc = proc

    result = StepResult(
        name="playback", status=StepStatus.SUCCESS,
        started_at=started_at, ended_at=started_at, duration_sec=0.0,
        message="Playback launched in background (PID {})".format(proc.pid),
        artifacts={
            "playback_pid": proc.pid,
            "local_dataset_path": context.local_dataset_path or "",
            "topics": list(config.playback_topics),
            "loop_enabled": False,
        },
    )
    step_results.append(result)
    return result


def _wait_background_playback(
    proc: "subprocess.Popen", context: RunContext, config: ToolConfig,
    step_results: List[StepResult],
) -> StepResult:
    """等待后台回灌子进程完成并收集结果。"""
    import time as _time_mod
    from datetime import datetime as _dt, timezone as _tz

    logger.info("Waiting for background playback (PID %s)...", proc.pid)
    started_at = _dt.now(_tz.utc).isoformat()
    _start = _time_mod.monotonic()

    try:
        stdout, stderr = proc.communicate(timeout=config.playback_timeout_sec)
    except Exception as exc:
        _end = _time_mod.monotonic()
        logger.error("Playback wait failed: %s", exc)
        try:
            proc.kill()
        except Exception:
            pass
        result = StepResult(
            name="playback", status=StepStatus.FAILED,
            started_at=started_at, ended_at=_dt.now(_tz.utc).isoformat(),
            duration_sec=_end - _start,
            message="Playback failed: {}".format(exc),
            error_type="TimeoutError",
        )
        _replace_launched_step(step_results, "playback", result)
        return result

    rc = proc.returncode
    elapsed = _time_mod.monotonic() - _start

    if rc != 0:
        logger.error("Playback failed: rc=%d", rc)
        result = StepResult(
            name="playback", status=StepStatus.FAILED,
            started_at=started_at, ended_at=_dt.now(_tz.utc).isoformat(),
            duration_sec=elapsed,
            message="Playback failed with rc={}".format(rc),
            error_type="CommandExecutionError",
        )
        _replace_launched_step(step_results, "playback", result)
        return result

    logger.info("Playback completed (rc=%d, elapsed=%.1fs)", rc, elapsed)
    result = StepResult(
        name="playback", status=StepStatus.SUCCESS,
        started_at=started_at, ended_at=_dt.now(_tz.utc).isoformat(),
        duration_sec=elapsed, message="Playback completed successfully",
        artifacts={
            "local_dataset_path": context.local_dataset_path or "",
            "topics": list(config.playback_topics),
            "loop_enabled": False,
        },
    )
    _replace_launched_step(step_results, "playback", result)
    return result


def _replace_launched_step(step_results: List[StepResult], name: str, new_result: StepResult) -> None:
    for i in range(len(step_results) - 1, -1, -1):
        if step_results[i].name == name:
            step_results[i] = new_result
            return


def _terminate_playback(proc: "subprocess.Popen") -> None:
    try:
        proc.kill()
        logger.info("Terminated background playback (PID %s)", proc.pid)
    except Exception:
        pass


def _cleanup_stop_recorder(
    context: RunContext, config: ToolConfig, step_results: List[StepResult],
) -> None:
    try:
        cleanup = step_runner.run_step(
            "stop_recorder", context,
            partial(recorder.stop_recorder, config=config),
        )
        step_results.append(cleanup)
        if cleanup.status == StepStatus.FAILED:
            logger.warning("Recorder cleanup also failed: %s", cleanup.message)
        else:
            logger.info("Recorder cleanup succeeded after failure.")
    except Exception as exc:
        logger.error("Exception during recorder cleanup: %s", exc)
        step_results.append(StepResult(
            name="stop_recorder", status=StepStatus.FAILED,
            started_at="", ended_at="", duration_sec=0.0,
            message=f"Cleanup exception: {exc}",             error_type="CleanupError",
        ))


# ── NAS 上传 ──

_NAS_BENCH_ROOT = "/media/nas/mdrive4/bench_smoke_test"


def _upload_batch_to_nas(config: ToolConfig, batch_dir: str, summaries: list) -> None:
    """将本次批次目录上传到 NAS（sudo 非交互执行，CIFS 挂载需 root 写权限）。

    上传前确认 NAS 挂载点可用；目标若已存在则跳过（不覆盖不删除）。
    dataset 子目录在 NAS 上仅保留 dataset_id（去掉 __short_name 避免中文乱码）。
    失败时仅记录 warning，不阻断 run 结果。
    """
    import os as _os_mod
    import shlex as _shlex
    from bench_smoke.command_runner import run_remote as _run_remote

    if not _os_mod.path.ismount(config.mount_check_path):
        logger.warning(
            "NAS not mounted at %s; skipping batch upload. "
            "Results remain at %s",
            config.mount_check_path, batch_dir,
        )
        return

    _nas_batch = _os_mod.path.join(_NAS_BENCH_ROOT, _os_mod.path.basename(batch_dir))
    if _os_mod.path.exists(_nas_batch):
        logger.warning(
            "Upload destination already exists (%s). Skipping upload. "
            "Local results remain at %s",
            _nas_batch, batch_dir,
        )
        return

    # 构造上传命令链：mkdir → copy batch_summary → cp -a 每条 dataset（NAS 目录名仅保留 dataset_id）
    _cmds = "sudo mkdir -p {}".format(_shlex.quote(_nas_batch))
    for _fname in ("batch_summary.txt", "batch_summary.json"):
        _src = _os_mod.path.join(batch_dir, _fname)
        if _os_mod.path.isfile(_src):
            _cmds += " && sudo cp {} {}".format(
                _shlex.quote(_src),
                _shlex.quote(_os_mod.path.join(_nas_batch, _fname)),
            )

    for _ent in sorted(_os_mod.listdir(batch_dir)):
        _full = _os_mod.path.join(batch_dir, _ent)
        if not _os_mod.path.isdir(_full):
            continue
        # _ent 形如 "7037566695__鬼探头二轮车" → NAS 上仅保留 "7037566695"
        _nas_name = _ent.split("__", 1)[0]
        _cmds += " && sudo cp -a {} {}".format(
            _shlex.quote(_full),
            _shlex.quote(_os_mod.path.join(_nas_batch, _nas_name)),
        )

    _upload_timeout = config.command_timeout_sec * 20  # 上传可慢（CIFS + 大文件）
    try:
        _run_remote(
            host=config.soc2_host, port=config.soc2_port,
            user=config.soc2_user, password=config.ssh_password,
            remote_command=_cmds,
            timeout_sec=_upload_timeout, check=False,
        )
        logger.info("Batch uploaded to NAS: %s", _nas_batch)
    except Exception as exc:
        logger.warning(
            "Failed to upload batch to NAS (%s). "
            "Results remain at %s",
            exc, batch_dir,
        )


def _write_batch_summary(batch_dir: str, summaries: list, install_result=None,
                         module_switch_result=None) -> None:
    """在批次目录写入 batch_summary.json（结构化）和 batch_summary.txt（终端可读）。

    install_result     — 批次级 install_packages 的 StepResult
    module_switch_result — 批次级 switch_to_playback_mode 的 StepResult
    """
    import json as _json_mod
    from datetime import datetime as _dt_mod

    total = len(summaries)
    success = sum(1 for s in summaries if s.status == StepStatus.SUCCESS)
    failed = total - success

    # --- batch_summary.json (structured dict for future HTML / auto-processing) ---
    json_payload = {
        "batch_dir": batch_dir,
        "generated_at": _dt_mod.now().isoformat(),
        "total": total,
        "success": success,
        "failed": failed,
        "datasets": [
            {
                "run_id": s.run_id,
                "dataset_id": s.dataset_id,
                "issue_description": s.issue_description,
                "short_name": getattr(s, "short_name", ""),
                "status": s.status.value,
                "failed_step": s.failed_step,
                "feishu_url": s.feishu_url,
            }
            for s in summaries
        ],
    }
    if install_result is not None:
        json_payload["install"] = {
            "status": install_result.status.value,
            "message": install_result.message,
            "duration_sec": install_result.duration_sec,
        }
    if module_switch_result is not None:
        json_payload["module_switch"] = {
            "status": module_switch_result.status.value,
            "message": module_switch_result.message,
            "duration_sec": module_switch_result.duration_sec,
        }
    json_path = os.path.join(batch_dir, "batch_summary.json")
    try:
        os.makedirs(batch_dir, exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as fh:
            _json_mod.dump(json_payload, fh, indent=2, ensure_ascii=False)
    except Exception as exc:
        logger.warning("Failed to write batch_summary.json: %s", exc)

    # --- batch_summary.txt (human-readable) ---
    txt_path = os.path.join(batch_dir, "batch_summary.txt")
    lines: list = []
    lines.append("=" * 72)
    lines.append("BENCH SMOKE BATCH SUMMARY")
    lines.append("=" * 72)
    lines.append(f"  Batch Dir    : {batch_dir}")
    if install_result is not None:
        inst_marker = "PASS" if install_result.status == StepStatus.SUCCESS else "FAIL"
        lines.append(f"  Install       : [{inst_marker}] {install_result.message}")
    if module_switch_result is not None:
        sw_marker = "PASS" if module_switch_result.status == StepStatus.SUCCESS else "FAIL"
        lines.append(f"  Module Switch : [{sw_marker}] {module_switch_result.message}")
    lines.append(f"  Total        : {total}")
    lines.append(f"  Success      : {success}")
    lines.append(f"  Failed       : {failed}")
    lines.append("")
    lines.append(f"  {'Status':<7s} {'Dataset ID':<14s} Name / Failed Step")
    lines.append(f"  {'------':<7s} {'----------':<14s} -----------------")
    for s in summaries:
        marker = "OK" if s.status == StepStatus.SUCCESS else "FAIL"
        display_name = getattr(s, "short_name", s.issue_description) or s.dataset_id
        detail = ""
        if s.failed_step:
            detail = f" => {s.failed_step}"
        lines.append(f"  [{marker:<4s}] {s.dataset_id:<14s} {display_name}{detail}")
    lines.append("")
    lines.append("=" * 72)

    try:
        os.makedirs(batch_dir, exist_ok=True)
        with open(txt_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        logger.info("Batch summary written to %s", batch_dir)
    except Exception as exc:
        logger.warning("Failed to write batch_summary.txt: %s", exc)


# ── mcap 后处理辅助：sudo 清理 recorder 原始文件（root-owned） ──

def _sudo_remove_file(config: ToolConfig, path: str) -> None:
    """Remove a single file, falling back to sudo for root-owned recorder output."""
    import shlex
    from bench_smoke.command_runner import run_remote
    try:
        os.remove(path)
    except PermissionError:
        run_remote(
            host=config.soc2_host, port=config.soc2_port,
            user=config.soc2_user, password=config.ssh_password,
            remote_command="sudo rm -f {}".format(shlex.quote(path)),
            timeout_sec=config.command_timeout_sec, check=False,
        )
    except Exception as exc:
        logger.warning("Failed to remove source mcap %s: %s", path, exc)


def _sudo_rmtree(config: ToolConfig, path: str) -> None:
    """Recursively remove a directory tree, falling back to sudo rm -rf."""
    import shlex
    import shutil as _shutil
    from bench_smoke.command_runner import run_remote
    try:
        _shutil.rmtree(path, ignore_errors=True)
    except PermissionError:
        pass
    if os.path.isdir(path):
        try:
            run_remote(
                host=config.soc2_host, port=config.soc2_port,
                user=config.soc2_user, password=config.ssh_password,
                remote_command="sudo rm -rf {}".format(shlex.quote(path)),
                timeout_sec=config.command_timeout_sec, check=False,
            )
            logger.info("Cleaned recorder output directory: %s", path)
        except Exception as exc:
            logger.warning("Failed to clean recorder directory %s: %s", path, exc)


def _build_and_write_summary(
    context: RunContext, dataset: DatasetEntry, packages: List[PackageSpec],
    step_results: List[StepResult], failed_step: Optional[str], config: ToolConfig,
) -> RunSummary:
    import shutil
    import os

    any_failed = any(r.status == StepStatus.FAILED for r in step_results)
    overall = StepStatus.FAILED if any_failed else StepStatus.SUCCESS

    # mcap 后处理：按文件大小选主 mcap，move 到 run_dir，清理 recorder 原始目录
    primary_mcap: Optional[str] = None
    if context.generated_mcaps and not failed_step:
        _source = max(
            context.generated_mcaps,
            key=lambda p: os.path.getsize(p) if os.path.isfile(p) else 0,
        )
        _dest = os.path.join(
            context.run_dir,
            "playback_{}_{}.mcap".format(
                dataset.dataset_id, context.batch_timestamp,
            ),
        )
        _rec_dir = os.path.dirname(_source)

        try:
            # move: 尝试 os.rename（同文件系统），权限不足时退化为 copy + sudo rm
            try:
                shutil.move(_source, _dest)
            except (PermissionError, OSError):
                shutil.copy2(_source, _dest)
                _sudo_remove_file(config, _source)
            primary_mcap = _dest
            logger.info("Primary mcap moved to %s", _dest)
        except Exception as exc:
            logger.warning("Failed to move primary mcap: %s", exc)

        # 清理整个 recorder 输出目录（含尾段等）
        if primary_mcap:
            _sudo_rmtree(config, _rec_dir)

    # 构建 generated_mcaps：集中后的路径在前，原路径在后
    final_mcaps: List[str] = []
    if primary_mcap:
        final_mcaps.append(primary_mcap)
    final_mcaps.extend(context.generated_mcaps)

    summary = RunSummary(
        run_id=context.run_id, dataset_id=dataset.dataset_id,
        issue_description=dataset.issue_description,
        feishu_url=dataset.feishu_url,
        status=overall, failed_step=failed_step,
        packages=list(packages), source_path=dataset.source_path,
        local_dataset_path=context.local_dataset_path,
        record_output_dir=context.record_output_dir,
        generated_mcaps=final_mcaps,
        step_results=step_results, summary_path=context.run_dir,
    )
    result_store.write_summary(summary)

    # 失败时：写入 execution.json 供排障
    if failed_step:
        result_store.write_execution_json(context, step_results)

    logger.info("Run summary written — run_id=%s status=%s failed_step=%s",
                context.run_id, overall.value, failed_step)
    return summary
