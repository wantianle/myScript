#!/usr/bin/env python3
"""Prepare per-record config folders from a vehicle-grouped record map."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any


DEFAULT_MDRIVE_CONF_REPO = Path("~/dev/mdrive_conf").expanduser()
DEFAULT_VEHICLE_CONFIG_NAME = "vehicle_config.pb.txt"
COMMIT_RE = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{8}(?![0-9a-fA-F])")
DATE_DIR_RE = re.compile(r"\d{8}")
VEHICLE_RE = re.compile(r"X[A-Z]{2,3}\d{6,8}")
COLOR_RESET = "\033[0m"
COLOR_DIM = "\033[2m"
COLOR_GREEN = "\033[32m"
COLOR_YELLOW = "\033[33m"
COLOR_RED = "\033[31m"
COLOR_CYAN = "\033[36m"


@dataclass(frozen=True)
class BranchInfo:
    platform: str
    git_branch: str
    git_ref: str
    commit_hash: str | None


@dataclass(frozen=True)
class ConfigTask:
    vehicle_key: str
    case_record_path: Path
    raw_record_path: Path | None
    version_path: Path
    config_dir: Path
    version_output_path: Path
    vehicle_config_output_path: Path
    version_vehicle: str
    branch_info: BranchInfo
    repo_config_path: str
    match_status: str


@dataclass(frozen=True)
class Failure:
    stage: str
    case_record_path: str
    vehicle: str
    branch: str
    ref: str
    error: str


class GitSwitchError(RuntimeError):
    def __init__(self, repo: Path, branch: str, stderr: str) -> None:
        self.repo = repo
        self.branch = branch
        self.stderr = stderr.strip()
        super().__init__(self.stderr or f"git switch failed for branch {branch}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read a record_vehicle_mapper JSON file and create one .config "
            "folder beside each case record with the source version file and "
            "the matching vehicle_config.pb.txt from mdrive_conf."
        )
    )
    parser.add_argument("input_json", type=Path, help="JSON produced by record_vehicle_mapper.py")
    parser.add_argument(
        "--repo",
        type=Path,
        default=DEFAULT_MDRIVE_CONF_REPO,
        help=f"mdrive_conf git repo. Default: {DEFAULT_MDRIVE_CONF_REPO}",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned actions without writing files or running git switch/show.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Do not print progress lines.",
    )
    parser.add_argument(
        "--vehicle-config-name",
        default=DEFAULT_VEHICLE_CONFIG_NAME,
        help=f"Output vehicle config filename. Default: {DEFAULT_VEHICLE_CONFIG_NAME}",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


class ProgressLogger:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def __call__(self, message: str) -> None:
        if self.enabled:
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"{COLOR_DIM}[{timestamp}]{COLOR_RESET} {message}", file=sys.stderr, flush=True)


def color(text: str, color_code: str) -> str:
    return f"{color_code}{text}{COLOR_RESET}"


def split_platform_tail(branch_text: str) -> tuple[str, str]:
    parts = branch_text.split(".", 4)
    platform = parts[0].strip()
    tail = parts[4].strip() if len(parts) == 5 else ""
    return platform, tail


def parse_branch_from_tail(tail: str) -> tuple[str | None, str | None]:
    if not tail:
        return None, None

    match = COMMIT_RE.search(tail)
    if not match:
        return tail, None

    branch = tail[: match.start()].rstrip("_")
    return branch or None, match.group(0)


def parse_branch_info(version_info: dict[str, Any]) -> BranchInfo:
    version_text = str(version_info.get("version") or "").strip()
    if not version_text:
        raise ValueError("version_info.version is missing")

    platform, tail = split_platform_tail(version_text)
    if not platform:
        raise ValueError(f"cannot parse platform from version_info.version: {version_text!r}")

    tail_branch, commit_hash = parse_branch_from_tail(tail)
    git_branch = str(version_info.get("branch") or "").strip() or tail_branch
    if not git_branch:
        raise ValueError(
            f"cannot parse git branch from version_info.version: {version_text!r}"
        )

    git_ref = commit_hash or "HEAD"
    return BranchInfo(
        platform=platform,
        git_branch=git_branch,
        git_ref=git_ref,
        commit_hash=commit_hash,
    )


def find_vehicle_in_parts(parts: tuple[str, ...]) -> str | None:
    for part in parts:
        if VEHICLE_RE.fullmatch(part):
            return part
    return None


def extract_vehicle_from_version_path(version_path: Path, fallback_vehicle: str) -> str:
    parts = version_path.parts

    if "00.raw" in parts:
        marker_index = parts.index("00.raw")
        tail = parts[marker_index + 1 :]
        for index, part in enumerate(tail[:-1]):
            if DATE_DIR_RE.fullmatch(part):
                candidate = tail[index + 1]
                if VEHICLE_RE.fullmatch(candidate):
                    return candidate
        found = find_vehicle_in_parts(tail)
        return found or fallback_vehicle

    if "01.load_test" in parts:
        marker_index = parts.index("01.load_test")
        found = find_vehicle_in_parts(parts[marker_index + 1 :])
        return found or fallback_vehicle

    if "01.road_test" in parts:
        marker_index = parts.index("01.road_test")
        tail = parts[marker_index + 1 :]
        if tail and VEHICLE_RE.fullmatch(tail[0]):
            return tail[0]
        found = find_vehicle_in_parts(tail)
        return found or fallback_vehicle

    found = find_vehicle_in_parts(parts)
    return found or fallback_vehicle


def build_repo_config_path(platform: str, vehicle: str, vehicle_config_name: str) -> str:
    return str(
        PurePosixPath(platform)
        / "vehicle_name"
        / vehicle
        / vehicle_config_name
    )


def iter_vehicle_entries(payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    vehicles = payload.get("vehicles")
    if not isinstance(vehicles, dict):
        raise ValueError("input JSON must contain a top-level 'vehicles' object")

    entries: list[tuple[str, dict[str, Any]]] = []
    for vehicle_key, vehicle_entries in vehicles.items():
        if not isinstance(vehicle_entries, list):
            continue
        for entry in vehicle_entries:
            if isinstance(entry, dict):
                entries.append((str(vehicle_key), entry))
    return entries


def build_task(
    vehicle_key: str,
    entry: dict[str, Any],
    vehicle_config_name: str,
) -> ConfigTask:
    case_record_value = entry.get("case_record_path")
    version_value = entry.get("version_path")
    if not case_record_value:
        raise ValueError("case_record_path is missing")
    if not version_value:
        raise ValueError("version_path is missing")

    version_info = entry.get("version_info")
    if not isinstance(version_info, dict):
        raise ValueError("version_info is missing or not an object")

    branch_info = parse_branch_info(version_info)
    case_record_path = Path(str(case_record_value))
    raw_record_value = entry.get("raw_record_path")
    raw_record_path = Path(str(raw_record_value)) if raw_record_value else None
    version_path = Path(str(version_value))
    version_vehicle = extract_vehicle_from_version_path(version_path, vehicle_key)
    config_dir = Path(str(case_record_path) + ".config")
    repo_config_path = build_repo_config_path(
        branch_info.platform, version_vehicle, vehicle_config_name
    )

    return ConfigTask(
        vehicle_key=vehicle_key,
        case_record_path=case_record_path,
        raw_record_path=raw_record_path,
        version_path=version_path,
        config_dir=config_dir,
        version_output_path=config_dir / version_path.name,
        vehicle_config_output_path=config_dir / vehicle_config_name,
        version_vehicle=version_vehicle,
        branch_info=branch_info,
        repo_config_path=repo_config_path,
        match_status=str(entry.get("match_status") or ""),
    )


def build_tasks(payload: dict[str, Any], vehicle_config_name: str) -> tuple[list[ConfigTask], list[str]]:
    tasks: list[ConfigTask] = []
    errors: list[str] = []
    for vehicle_key, entry in iter_vehicle_entries(payload):
        try:
            tasks.append(build_task(vehicle_key, entry, vehicle_config_name))
        except ValueError as exc:
            case_record = entry.get("case_record_path", "<unknown>")
            errors.append(f"{case_record}: {exc}")
    return tasks, errors


def copy_file(src: Path, dst: Path) -> str:
    if not src.is_file():
        raise FileNotFoundError(f"source file does not exist: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return "copied"


def run_git_switch(repo: Path, branch: str) -> None:
    try:
        subprocess.run(
            ["git", "-C", str(repo), "switch", branch],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as exc:
        raise GitSwitchError(repo, branch, exc.stderr or "") from exc


def read_git_file(repo: Path, ref: str, repo_path: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), "show", f"{ref}:{repo_path}"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout


def write_bytes(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return "written"


def format_task(task: ConfigTask) -> str:
    ref_note = task.branch_info.commit_hash or "HEAD"
    return (
        f"case={task.case_record_path} vehicle={task.version_vehicle} "
        f"branch={task.branch_info.git_branch} ref={ref_note} "
        f"repo_path={task.repo_config_path} config_dir={task.config_dir}"
    )


def failure_from_task(task: ConfigTask, stage: str, error: str) -> Failure:
    return Failure(
        stage=stage,
        case_record_path=str(task.case_record_path),
        vehicle=task.version_vehicle,
        branch=task.branch_info.git_branch,
        ref=task.branch_info.git_ref,
        error=error,
    )


def print_failures(failures: list[Failure]) -> None:
    if not failures:
        return
    print(color("failures:", COLOR_RED), file=sys.stderr)
    for index, failure in enumerate(failures, start=1):
        print(
            color(f"  {index}. stage={failure.stage}", COLOR_RED)
            + f" case={failure.case_record_path} vehicle={failure.vehicle} "
            f"branch={failure.branch} ref={failure.ref}",
            file=sys.stderr,
        )
        print(f"     error={failure.error}", file=sys.stderr)


def execute_task(
    task: ConfigTask,
    repo: Path,
    dry_run: bool,
    progress: ProgressLogger,
) -> tuple[bool, str]:
    if dry_run:
        return True, "DRY-RUN " + format_task(task)

    progress(color("create config dir:", COLOR_CYAN) + f" {task.config_dir}")
    task.config_dir.mkdir(parents=True, exist_ok=True)
    progress(
        color("copy version file:", COLOR_CYAN)
        + f" {task.version_path} -> {task.version_output_path}"
    )
    version_status = copy_file(task.version_path, task.version_output_path)
    progress(
        color("git switch:", COLOR_YELLOW)
        + f" branch={task.branch_info.git_branch} repo={repo}"
    )
    run_git_switch(repo, task.branch_info.git_branch)
    progress(
        color("git show:", COLOR_YELLOW)
        + f" ref={task.branch_info.git_ref} path={task.repo_config_path}"
    )
    data = read_git_file(repo, task.branch_info.git_ref, task.repo_config_path)
    progress(color("write vehicle config:", COLOR_CYAN) + f" {task.vehicle_config_output_path}")
    config_status = write_bytes(task.vehicle_config_output_path, data)
    return (
        True,
        (
            f"OK {task.case_record_path} "
            f"version={version_status} vehicle_config={config_status}"
        ),
    )


def main() -> int:
    args = parse_args()
    progress = ProgressLogger(not args.quiet)
    progress(color("loading input JSON:", COLOR_CYAN) + f" {args.input_json}")
    payload = load_json(args.input_json)
    tasks, build_errors = build_tasks(payload, args.vehicle_config_name)
    progress(
        color("task build done:", COLOR_CYAN)
        + f" tasks={len(tasks)} build_errors={len(build_errors)} "
        f"dry_run={args.dry_run}"
    )

    success_count = 0
    failure_count = len(build_errors)
    failures: list[Failure] = []
    for error in build_errors:
        failures.append(
            Failure(
                stage="build-task",
                case_record_path="<unknown>",
                vehicle="<unknown>",
                branch="<unknown>",
                ref="<unknown>",
                error=error,
            )
        )
        print(color("ERROR build-task", COLOR_RED) + f" {error}", file=sys.stderr)

    for index, task in enumerate(tasks, start=1):
        progress(
            color(f"task {index}/{len(tasks)}:", COLOR_CYAN)
            + f" vehicle={task.version_vehicle} "
            f"branch={task.branch_info.git_branch} ref={task.branch_info.git_ref} "
            f"case={task.case_record_path}"
        )
        try:
            ok, message = execute_task(task, args.repo, args.dry_run, progress)
        except GitSwitchError as exc:
            failure_count += 1
            failure = failure_from_task(
                task,
                "git-switch",
                f"repo={exc.repo} stderr={exc.stderr or exc}",
            )
            failures.append(failure)
            print_failures([failure])
            if exc.stderr:
                print(f"git stderr: {exc.stderr}", file=sys.stderr)
            print(
                color("summary:", COLOR_RED)
                + f" tasks={len(tasks)} success={success_count} "
                f"failed={failure_count} dry_run={args.dry_run}",
                file=sys.stderr,
            )
            return 1
        except (OSError, subprocess.CalledProcessError) as exc:
            ok = False
            message = f"ERROR {task.case_record_path}: {exc}"
            failures.append(failure_from_task(task, "execute", str(exc)))

        if ok:
            success_count += 1
            print(color(message, COLOR_GREEN))
        else:
            failure_count += 1
            print(color(message, COLOR_RED), file=sys.stderr)

    print_failures(failures)
    summary_color = COLOR_RED if failure_count else COLOR_GREEN
    print(
        color("summary:", summary_color)
        + f" tasks={len(tasks)} success={success_count} failed={failure_count} "
        f"dry_run={args.dry_run}"
    )
    return 1 if failure_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
