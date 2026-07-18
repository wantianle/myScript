# -*- coding: utf-8 -*-
"""运行输出目录管理与产物持久化。

创建每次运行的目录树，写入汇总、上下文快照、步骤执行明细。
"""

from __future__ import annotations

import dataclasses
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from enum import Enum

from bench_smoke.models import (
    DatasetEntry,
    PackageSpec,
    RunContext,
    RunSummary,
    StepResult,
    StepStatus,
    ToolConfig,
)


# 序列化辅助

class _DataclassEncoder(json.JSONEncoder):
    """支持 Enum 和 dataclass 的 JSON 编码器。"""

    def default(self, o: Any) -> Any:
        if isinstance(o, Enum):
            return o.value
        if dataclasses.is_dataclass(o) and not isinstance(o, type):
            return dataclasses.asdict(o)
        return super().default(o)


def _write_json(path: str, obj: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, cls=_DataclassEncoder, indent=2, ensure_ascii=False)


def _read_json(path: str) -> Any:
    """读取 JSON 文件，返回任意类型。"""
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# 运行上下文创建与持久化

def _resolve_batch_dir(run_root: str, timestamp: str) -> tuple:
    """为批次时间戳找到可用的目录路径，冲突时追加 _2, _3 等后缀。

    返回 (batch_dir_abs_path, resolved_timestamp_string)。
    """
    batch_dir = os.path.join(run_root, "runs", timestamp)
    if not os.path.exists(batch_dir):
        return batch_dir, timestamp

    for suffix in range(2, 100):
        resolved_ts = f"{timestamp}_{suffix}"
        candidate = os.path.join(run_root, "runs", resolved_ts)
        if not os.path.exists(candidate):
            return candidate, resolved_ts

    raise RuntimeError(
        f"Too many batch directory conflicts for timestamp '{timestamp}'. "
        "Please wait a minute and try again."
    )


def create_run_context(
    dataset: DatasetEntry,
    packages: List[PackageSpec],
    config: ToolConfig,
    batch_timestamp: Optional[str] = None,
) -> RunContext:
    """创建唯一运行目录并返回 RunContext。

    目录规则: {run_root}/runs/<YYYYMMDD_HHMM>/<dataset_id>__<short_name>/
    当 short_name 为空时回退为使用 dataset_id。

    若 batch_timestamp 由外部提供（如 run_batch 批次共享），
    则直接使用该时间戳，不再重新做冲突检测；
    否则由当前时间生成并进行自动冲突检测（_2, _3 后缀）。
    """
    if batch_timestamp is not None:
        batch_dir = os.path.join(config.run_root, "runs", batch_timestamp)
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        batch_dir, batch_timestamp = _resolve_batch_dir(config.run_root, ts)

    # type-narrowing: batch_timestamp is definitely a str here
    assert batch_timestamp is not None
    short_name = dataset.short_name if dataset.short_name else dataset.dataset_id
    dataset_dir_name = f"{dataset.dataset_id}__{short_name}"
    run_dir = os.path.join(batch_dir, dataset_dir_name)

    os.makedirs(run_dir, exist_ok=True)

    context = RunContext(
        run_id=dataset_dir_name,
        run_dir=run_dir,
        dataset=dataset,
        packages=list(packages),
        batch_timestamp=batch_timestamp,
    )

    save_context(context)
    return context


def save_context(context: RunContext) -> None:
    path = os.path.join(context.run_dir, "run_context.json")
    _write_json(path, context)


# 步骤执行明细持久化

def write_execution_json(context: RunContext, step_results: List[StepResult]) -> str:
    """将所有步骤结果写入单个 execution.json 文件，返回绝对路径。

    execution.json 替代了原来散落在 steps/ 目录下的多个步骤 JSON 文件，
    格式为一个 StepResult 数组，便于后续 HTML/report 消费。
    """
    path = os.path.join(context.run_dir, "execution.json")
    _write_json(path, step_results)
    return path


def load_step_results(context: RunContext) -> List[StepResult]:
    """加载已持久化的步骤结果。

    优先从 execution.json 读取，如不存在则回退到旧的 steps/ 目录
    （向后兼容旧运行）。
    """
    exec_path = os.path.join(context.run_dir, "execution.json")
    if os.path.isfile(exec_path):
        data_list: List[Dict[str, Any]] = _read_json(exec_path)
        results: List[StepResult] = []
        for item in data_list:
            item["status"] = StepStatus(str(item.get("status", "")))
            results.append(StepResult(**item))  # type: ignore[arg-type]
        return results

    # 向后兼容: 旧的 steps/ 目录
    steps_dir = os.path.join(context.run_dir, "steps")
    if not os.path.isdir(steps_dir):
        return []

    results = []
    for filename in sorted(os.listdir(steps_dir)):
        if not filename.endswith(".json"):
            continue
        path = os.path.join(steps_dir, filename)
        entry: Dict[str, Any] = _read_json(path)
        entry["status"] = StepStatus(str(entry.get("status", "")))
        results.append(StepResult(**entry))  # type: ignore[arg-type]
    return results


# 汇总持久化

def write_summary(summary: RunSummary) -> None:
    """写入 summary.json（机器可读）和 summary.txt（终端可读）。"""
    run_dir = summary.summary_path

    json_path = os.path.join(run_dir, "summary.json")
    _write_json(json_path, summary)

    txt_path = os.path.join(run_dir, "summary.txt")
    os.makedirs(run_dir, exist_ok=True)
    with open(txt_path, "w", encoding="utf-8") as fh:
        fh.write(_format_summary_text(summary))


def _format_summary_text(summary: RunSummary) -> str:
    lines: List[str] = []
    lines.append("=" * 72)
    lines.append("BENCH SMOKE RUN SUMMARY")
    lines.append("=" * 72)
    lines.append(f"  Run ID          : {summary.run_id}")
    lines.append(f"  Dataset ID      : {summary.dataset_id}")
    lines.append(f"  Description     : {summary.issue_description}")
    lines.append(f"  Feishu URL      : {summary.feishu_url}")
    lines.append(f"  Source Path     : {summary.source_path}")
    lines.append(f"  Status          : {summary.status.value.upper()}")
    if summary.failed_step:
        lines.append(f"  Failed Step     : {summary.failed_step}")
    if summary.local_dataset_path:
        lines.append(f"  Local Data Path : {summary.local_dataset_path}")
    if summary.record_output_dir:
        lines.append(f"  Record Output   : {summary.record_output_dir}")
    if summary.generated_mcaps:
        lines.append("  Generated MCAPs :")
        for mcap in summary.generated_mcaps:
            lines.append(f"    - {mcap}")
    lines.append("")

    if summary.packages:
        lines.append("  Packages:")
        for pkg in summary.packages:
            lines.append(f"    - {pkg.package} == {pkg.version}")
        lines.append("")

    lines.append("  Steps:")
    for step in summary.step_results:
        status_mark = {
            StepStatus.SUCCESS: "OK",
            StepStatus.FAILED: "FAIL",
            StepStatus.SKIPPED: "SKIP",
        }.get(step.status, "??")
        lines.append(
            f"    [{status_mark:>4s}] {step.name:<24s} "
            f"({step.duration_sec:.1f}s)"
        )
        if step.message and step.status != StepStatus.SUCCESS:
            lines.append(f"          {step.message}")

    lines.append("")
    lines.append(f"  Summary written to: {summary.summary_path}")
    lines.append("=" * 72)
    return "\n".join(lines) + "\n"
