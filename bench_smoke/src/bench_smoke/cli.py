# -*- coding: utf-8 -*-
"""命令行入口。

子命令:
  bench-smoke run   — 一键完整流程
  bench-smoke debug — 单步排障执行

退出码: 0=成功, 1=工作流/步骤失败, 2=CLI/配置/清单错误
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from bench_smoke.config import load_config
from bench_smoke.logging_setup import setup_logging
from bench_smoke.manifest import load_manifest, load_manifest_packages, select_datasets
from bench_smoke.models import ManifestError, PackageSpec, StepStatus
from bench_smoke.orchestrator import run_debug_step, run_full, run_many


def _parse_package_specs(raw: List[str]) -> List[PackageSpec]:
    """解析 --package NAME=VERSION 参数为 PackageSpec 列表。"""
    specs: List[PackageSpec] = []
    for item in raw:
        parts = item.split(",", 1)
        core = parts[0].strip()
        with_deps = True
        if len(parts) == 2:
            flag = parts[1].strip().lower()
            with_deps = flag in ("1", "true", "yes")
        if "=" not in core:
            raise ValueError(f"Invalid package spec '{item}': expected NAME=VERSION format")
        pkg, ver = core.split("=", 1)
        pkg = pkg.strip()
        ver = ver.strip()
        if not pkg or not ver:
            raise ValueError(f"Invalid package spec '{item}': NAME and VERSION must be non-empty")
        specs.append(PackageSpec(package=pkg, version=ver, install_with_deps=with_deps))
    return specs


def _resolve_packages(args: argparse.Namespace, manifest_path: str) -> List[PackageSpec]:
    """package 列表：命令行优先，其次 manifest 顶层，都没有则报错。"""
    if args.package:
        try:
            return _parse_package_specs(args.package)
        except ValueError as exc:
            print(f"Package parsing error: {exc}", file=sys.stderr)
            sys.exit(2)

    pkgs = load_manifest_packages(manifest_path)
    if pkgs:
        return pkgs

    print(
        "No packages specified.  Use --package NAME=VERSION, "
        "or add a top-level 'packages' list to the manifest.",
        file=sys.stderr,
    )
    sys.exit(2)


def _resolve_datasets(args: argparse.Namespace, all_entries) -> list:
    """解析数据集选择。

    --dataset-id 支持单个、多次、逗号分隔。
    未指定时返回 manifest 全部数据集。
    重复 ID 去重，结果按 manifest 原顺序排列。
    """
    if not args.dataset_id:
        return list(all_entries)

    ids: List[str] = []
    raw = args.dataset_id
    if isinstance(raw, list):
        for item in raw:
            ids.extend(did.strip() for did in str(item).split(",") if did.strip())
    else:
        ids.extend(did.strip() for did in str(raw).split(",") if did.strip())

    seen: set = set()
    unique: List[str] = []
    for did in ids:
        if did not in seen:
            seen.add(did)
            unique.append(did)

    return select_datasets(all_entries, unique)


def _setup_console_logging() -> None:
    try:
        setup_logging("", console=True)
    except Exception:
        pass


def _cmd_run(args: argparse.Namespace) -> int:
    config = load_config()

    try:
        all_entries = load_manifest(args.manifest)
    except ManifestError as exc:
        print(f"Manifest error: {exc}", file=sys.stderr)
        return 2

    try:
        datasets = _resolve_datasets(args, all_entries)
    except ManifestError as exc:
        print(f"Dataset selection error: {exc}", file=sys.stderr)
        return 2

    try:
        packages = _resolve_packages(args, args.manifest)
    except SystemExit:
        return 2

    _setup_console_logging()

    try:
        if len(datasets) == 1:
            summary = run_full(datasets[0], packages, config)
            return 0 if summary.status == StepStatus.SUCCESS else 1
        else:
            summaries = run_many(datasets, packages, config)
            return 0 if summaries and summaries[-1].status == StepStatus.SUCCESS else 1
    except Exception as exc:
        print(f"Unexpected error during execution: {exc}", file=sys.stderr)
        return 1


def _cmd_debug(args: argparse.Namespace) -> int:
    config = load_config()

    try:
        all_entries = load_manifest(args.manifest)
    except ManifestError as exc:
        print(f"Manifest error: {exc}", file=sys.stderr)
        return 2

    try:
        datasets = _resolve_datasets(args, all_entries)
    except ManifestError as exc:
        print(f"Dataset selection error: {exc}", file=sys.stderr)
        return 2

    try:
        packages = _resolve_packages(args, args.manifest)
    except SystemExit:
        return 2

    _setup_console_logging()

    # debug 模式：未指定 dataset-id 且 manifest 多条时，逐个执行
    final_status = 0
    for dataset in datasets:
        try:
            result = run_debug_step(
                step=args.step, dataset=dataset, packages=packages,
                config=config, run_id=args.run_id,
            )
        except ValueError as exc:
            print(f"Debug step error for {dataset.dataset_id}: {exc}", file=sys.stderr)
            return 2
        except Exception as exc:
            print(f"Unexpected error for {dataset.dataset_id}: {exc}", file=sys.stderr)
            return 1

        if result.status != StepStatus.SUCCESS:
            print(f"Debug step '{args.step}' FAILED for {dataset.dataset_id}: {result.message}")
            final_status = 1
        else:
            print(f"Debug step '{args.step}' OK for {dataset.dataset_id}")

    return final_status


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bench-smoke",
        description="Orin 域控台架每日开环冒烟测试工具",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="执行一键完整流程")
    run_p.add_argument("--manifest", required=True, help="数据集清单文件路径（YAML 或 JSON）")
    run_p.add_argument(
        "--dataset-id", action="append", dest="dataset_id", default=None,
        help="数据集 ID，支持多次指定或逗号分隔。不写默认跑全部",
    )
    run_p.add_argument(
        "--package", action="append", dest="package", default=None,
        help="版本包规格：NAME=VERSION。可省略（从 manifest 顶层 packages 读取）",
    )
    run_p.set_defaults(func=_cmd_run)

    debug_p = sub.add_parser("debug", help="执行单个步骤进行排障")
    debug_p.add_argument(
        "step",
        help="步骤名称: validate_manifest / inspect_version / install_version / "
             "prepare_data / switch_modules / start_recorder / playback / "
             "stop_recorder / collect_metadata / summarize",
    )
    debug_p.add_argument("--manifest", required=True, help="数据集清单文件路径")
    debug_p.add_argument(
        "--dataset-id", action="append", dest="dataset_id", default=None,
        help="数据集 ID，支持逗号分隔。不写默认跑全部",
    )
    debug_p.add_argument(
        "--package", action="append", dest="package", default=None,
        help="版本包规格：NAME=VERSION。可省略（从 manifest 顶层 packages 读取）",
    )
    debug_p.add_argument("--run-id", help="可选的已有运行 ID，用于恢复或检查")
    debug_p.set_defaults(func=_cmd_debug)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 2 if (exc.code is not None and exc.code != 0) else 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
