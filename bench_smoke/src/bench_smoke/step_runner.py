# -*- coding: utf-8 -*-
"""步骤执行包装器。

所有工作流步骤（一键模式或 debug 模式）均通过 run_step() 执行。
统一处理计时、异常捕获、结果归一化。不再自行持久化步骤明细，
由编排器在流程结束时统一决定是否写 execution.json。
"""

from __future__ import annotations

import logging
import time
import traceback
from datetime import datetime, timezone
from typing import Callable

from bench_smoke.models import StepResult, StepStatus, RunContext
import bench_smoke.result_store as result_store

logger = logging.getLogger("bench_smoke.step_runner")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_step(
    name: str,
    context: RunContext,
    fn: Callable[[RunContext], StepResult],
) -> StepResult:
    """执行单个工作流步骤，统一生命周期管理。

    1. 记录开始
    2. 调用 fn(context)，返回 StepResult
    3. 已知异常→FAILED，带 error_type
    4. 未知异常→FAILED，error_type="UnexpectedError"
    5. 持久化 RunContext 变更（local_dataset_path 等），
       但不写步骤明细文件（编排器在流程结束时统一写 execution.json）
    """
    started_at = _now_iso()
    t0 = time.monotonic()

    logger.info("Step started: %s", name)

    try:
        result = fn(context)
    except Exception as exc:
        ended_at = _now_iso()
        duration = time.monotonic() - t0

        from bench_smoke.models import BenchSmokeError
        if isinstance(exc, BenchSmokeError):
            error_type = type(exc).__name__
            message = str(exc)
        else:
            error_type = "UnexpectedError"
            message = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"

        logger.error("Step failed: %s — %s: %s", name, error_type, exc)

        result = StepResult(
            name=name,
            status=StepStatus.FAILED,
            started_at=started_at,
            ended_at=ended_at,
            duration_sec=duration,
            message=message,
            error_type=error_type,
        )

        # 即使步骤失败，也持久化 context 变更
        try:
            result_store.save_context(context)
        except Exception:
            pass
        return result

    if not result.ended_at:
        result.ended_at = _now_iso()
    if result.duration_sec <= 0:
        result.duration_sec = time.monotonic() - t0

    if not result.started_at:
        result.started_at = started_at

    status_label = result.status.value.upper() if result.status else "??"
    logger.info(
        "Step finished: %s — %s (%.1fs)",
        name, status_label, result.duration_sec,
    )

    try:
        result_store.save_context(context)
    except Exception:
        pass
    return result
