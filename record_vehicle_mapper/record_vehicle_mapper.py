#!/usr/bin/env python3
"""Map soc record files back to raw storage paths and vehicle versions."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable


DEFAULT_CASE_ROOT = Path("/media/pnc_team-planning_algo-driving/L4_cases")
DEFAULT_RAW_ROOT = Path("/media/nas/00.raw")
DEFAULT_ROAD_TEST_ROOT = Path("/media/nas/04.mdrive3/01.road_test")
DEFAULT_OUTPUT = Path("record_vehicle_map.json")
DEFAULT_RECORD_REGEX = r"\d{14}\.record\.\d{5}\.\d{6}(?:\.split)?"
DEFAULT_VERSION_FILENAMES = ("version.json", "version.txt")
RAW_SOURCE = "00.raw"
ROAD_TEST_SOURCE = "04.mdrive3_road_test"
DATE_DIR_RE = re.compile(r"\d{8}")
RECORD_DATE_RE = re.compile(r"^(\d{8})")
TOKEN_STRIP_CHARS = " \t\r\n,;:'\"[]{}()"


@dataclass(frozen=True)
class RawMatch:
    path: Path
    source: str
    source_root: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Find record files under L4_cases soc2, locate their original raw "
            "paths under 00.raw, extract the vehicle id, and write a JSON map."
        )
    )
    parser.add_argument(
        "--case-root",
        type=Path,
        default=DEFAULT_CASE_ROOT,
        help=f"L4 cases root. Default: {DEFAULT_CASE_ROOT}",
    )
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=DEFAULT_RAW_ROOT,
        help=f"Raw record root. Default: {DEFAULT_RAW_ROOT}",
    )
    parser.add_argument(
        "--road-test-root",
        type=Path,
        default=DEFAULT_ROAD_TEST_ROOT,
        help=f"Road-test raw root. Default: {DEFAULT_ROAD_TEST_ROOT}",
    )
    parser.add_argument(
        "--soc",
        default="soc2",
        help="Only scan records below directories with this name. Default: soc2",
    )
    parser.add_argument(
        "--exclude-dir",
        action="append",
        default=[],
        help=(
            "Directory basename to skip while scanning case records. "
            "Can be repeated, for example: --exclude-dir odom数据包"
        ),
    )
    parser.add_argument(
        "--record-regex",
        default=DEFAULT_RECORD_REGEX,
        help=f"Record basename regex. Default: {DEFAULT_RECORD_REGEX}",
    )
    parser.add_argument(
        "--version-filename",
        action="append",
        dest="version_filenames",
        help=(
            "Version filename to look for in the raw record directory. "
            "Can be repeated. Default: version.json, version.txt"
        ),
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output JSON path. Default: {DEFAULT_OUTPUT}",
    )
    parser.add_argument(
        "--follow-links",
        action="store_true",
        help="Follow symlinked directories while scanning.",
    )
    parser.add_argument(
        "--no-version-content",
        action="store_true",
        help="Only record version file paths, do not embed version file content.",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=2000,
        help="Print one progress line every N scanned directories. Default: 2000",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Do not print progress lines.",
    )
    return parser.parse_args()


def path_for_json(path: Path) -> str:
    return str(path.absolute())


def compile_record_regex(pattern: str) -> re.Pattern[str]:
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"invalid --record-regex {pattern!r}: {exc}") from exc


def require_dir(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} does not exist: {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"{label} is not a directory: {path}")


class ProgressLogger:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def __call__(self, message: str) -> None:
        if self.enabled:
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] {message}", file=sys.stderr, flush=True)


def is_below_named_dir(path: Path, dir_name: str) -> bool:
    return dir_name in path.parts


def extract_record_date(record_name: str) -> str | None:
    match = RECORD_DATE_RE.match(record_name)
    if not match:
        return None

    record_date = match.group(1)
    if DATE_DIR_RE.fullmatch(record_date):
        return record_date
    return None


def group_record_names_by_date(
    record_names: set[str],
) -> tuple[dict[str, set[str]], set[str]]:
    names_by_date: dict[str, set[str]] = defaultdict(set)
    undated_names: set[str] = set()

    for record_name in record_names:
        record_date = extract_record_date(record_name)
        if record_date:
            names_by_date[record_date].add(record_name)
        else:
            undated_names.add(record_name)

    return names_by_date, undated_names


def next_date_text(record_date: str) -> str | None:
    try:
        date_value = datetime.strptime(record_date, "%Y%m%d")
    except ValueError:
        return None
    return (date_value + timedelta(days=1)).strftime("%Y%m%d")


def expand_record_names_to_raw_search_dates(
    target_names_by_date: dict[str, set[str]]
) -> dict[str, set[str]]:
    expanded: dict[str, set[str]] = defaultdict(set)
    for record_date, target_names in target_names_by_date.items():
        expanded[record_date].update(target_names)
        next_day = next_date_text(record_date)
        if next_day:
            expanded[next_day].update(target_names)
    return expanded


def shift_record_names_to_next_day(
    target_names_by_date: dict[str, set[str]]
) -> dict[str, set[str]]:
    shifted: dict[str, set[str]] = defaultdict(set)
    for record_date, target_names in target_names_by_date.items():
        next_day = next_date_text(record_date)
        if next_day:
            shifted[next_day].update(target_names)
    return shifted


def scan_case_records(
    case_root: Path,
    soc_name: str,
    record_re: re.Pattern[str],
    follow_links: bool,
    scan_errors: list[dict[str, str]],
    exclude_dirs: set[str] | None = None,
    progress: Callable[[str], None] | None = None,
    progress_interval: int = 2000,
) -> list[Path]:
    records: list[Path] = []
    scanned_dirs = 0
    skipped_dirs = 0
    exclude_dirs = exclude_dirs or set()
    progress_interval = max(progress_interval, 1)

    def on_error(exc: OSError) -> None:
        scan_errors.append({"path": str(exc.filename), "error": str(exc)})

    if progress:
        exclude_text = ", ".join(sorted(exclude_dirs)) if exclude_dirs else "none"
        progress(
            f"scanning case records under {case_root} "
            f"(soc={soc_name}, exclude_dirs={exclude_text})"
        )

    for root, dirnames, filenames in os.walk(
        case_root, followlinks=follow_links, onerror=on_error
    ):
        scanned_dirs += 1
        if exclude_dirs:
            before_count = len(dirnames)
            dirnames[:] = [
                dirname for dirname in dirnames if dirname not in exclude_dirs
            ]
            skipped_dirs += before_count - len(dirnames)

        root_path = Path(root)
        if not is_below_named_dir(root_path, soc_name):
            if progress and scanned_dirs % progress_interval == 0:
                progress(
                    f"case scan: dirs={scanned_dirs}, skipped_dirs={skipped_dirs}, "
                    f"records={len(records)}, current={root_path}"
                )
            continue

        for filename in filenames:
            if record_re.fullmatch(filename):
                records.append(root_path / filename)

        if progress and scanned_dirs % progress_interval == 0:
            progress(
                f"case scan: dirs={scanned_dirs}, skipped_dirs={skipped_dirs}, "
                f"records={len(records)}, current={root_path}"
            )

    if progress:
        progress(
            f"case scan done: dirs={scanned_dirs}, skipped_dirs={skipped_dirs}, "
            f"records={len(records)}"
        )

    return sorted(records, key=lambda item: str(item))


def scan_raw_records(
    raw_root: Path,
    target_names_by_date: dict[str, set[str]],
    follow_links: bool,
    scan_errors: list[dict[str, str]],
    progress: Callable[[str], None] | None = None,
    progress_interval: int = 2000,
) -> dict[str, list[RawMatch]]:
    raw_index: dict[str, list[RawMatch]] = defaultdict(list)
    if not target_names_by_date:
        return raw_index

    if not raw_root.is_dir():
        if progress:
            progress(f"raw root missing, skip: {raw_root}")
        return raw_index

    progress_interval = max(progress_interval, 1)

    def on_error(exc: OSError) -> None:
        scan_errors.append({"path": str(exc.filename), "error": str(exc)})

    date_items = sorted(target_names_by_date.items())
    if progress:
        progress(f"scanning raw records by date under {raw_root}: dates={len(date_items)}")

    for date_index, (record_date, target_names) in enumerate(date_items, start=1):
        date_root = raw_root / record_date
        if not date_root.is_dir():
            if progress:
                progress(
                    f"raw scan {date_index}/{len(date_items)}: missing {date_root} "
                    f"(records={len(target_names)})"
                )
            continue

        if progress:
            progress(
                f"raw scan {date_index}/{len(date_items)}: {date_root} "
                f"(target_records={len(target_names)})"
            )

        scanned_dirs = 0
        date_matches = 0
        for root, _dirnames, filenames in os.walk(
            date_root, followlinks=follow_links, onerror=on_error
        ):
            scanned_dirs += 1
            filename_set = set(filenames)
            for record_name in sorted(target_names.intersection(filename_set)):
                raw_index[record_name].append(
                    RawMatch(Path(root) / record_name, RAW_SOURCE, raw_root)
                )
                date_matches += 1

            if progress and scanned_dirs % progress_interval == 0:
                progress(
                    f"raw scan {record_date}: dirs={scanned_dirs}, "
                    f"matches={date_matches}, current={root}"
                )

        if progress:
            progress(
                f"raw scan {record_date} done: dirs={scanned_dirs}, "
                f"matches={date_matches}"
            )

    return {
        record_name: sorted(matches, key=lambda item: (item.source, str(item.path)))
        for record_name, matches in raw_index.items()
    }


def scan_road_test_records(
    road_test_root: Path,
    target_names_by_date: dict[str, set[str]],
    follow_links: bool,
    scan_errors: list[dict[str, str]],
    progress: Callable[[str], None] | None = None,
    progress_interval: int = 2000,
) -> dict[str, list[RawMatch]]:
    raw_index: dict[str, list[RawMatch]] = defaultdict(list)
    if not target_names_by_date:
        return raw_index

    if not road_test_root.is_dir():
        if progress:
            progress(f"road-test root missing, skip: {road_test_root}")
        return raw_index

    progress_interval = max(progress_interval, 1)
    target_names_by_year: dict[str, set[str]] = defaultdict(set)
    for record_date, target_names in target_names_by_date.items():
        target_names_by_year[record_date[:4]].update(target_names)

    def on_error(exc: OSError) -> None:
        scan_errors.append({"path": str(exc.filename), "error": str(exc)})

    vehicle_dirs = sorted(path for path in road_test_root.iterdir() if path.is_dir())
    if progress:
        progress(
            f"scanning road-test records under {road_test_root}: "
            f"vehicles={len(vehicle_dirs)}, years={len(target_names_by_year)}"
        )

    for vehicle_index, vehicle_dir in enumerate(vehicle_dirs, start=1):
        for record_year, target_names in sorted(target_names_by_year.items()):
            year_root = vehicle_dir / record_year
            if not year_root.is_dir():
                continue

            if progress:
                progress(
                    f"road-test scan vehicle {vehicle_index}/{len(vehicle_dirs)}: "
                    f"{year_root} (target_records={len(target_names)})"
                )

            scanned_dirs = 0
            year_matches = 0
            for root, _dirnames, filenames in os.walk(
                year_root, followlinks=follow_links, onerror=on_error
            ):
                scanned_dirs += 1
                filename_set = set(filenames)
                for record_name in sorted(target_names.intersection(filename_set)):
                    raw_index[record_name].append(
                        RawMatch(Path(root) / record_name, ROAD_TEST_SOURCE, road_test_root)
                    )
                    year_matches += 1

                if progress and scanned_dirs % progress_interval == 0:
                    progress(
                        f"road-test scan {year_root}: dirs={scanned_dirs}, "
                        f"matches={year_matches}, current={root}"
                    )

            if progress:
                progress(
                    f"road-test scan {year_root} done: dirs={scanned_dirs}, "
                    f"matches={year_matches}"
                )

    return {
        record_name: sorted(matches, key=lambda item: (item.source, str(item.path)))
        for record_name, matches in raw_index.items()
    }


def merge_raw_indexes(*indexes: dict[str, list[RawMatch]]) -> dict[str, list[RawMatch]]:
    merged: dict[str, list[RawMatch]] = defaultdict(list)
    for index in indexes:
        for record_name, matches in index.items():
            merged[record_name].extend(matches)

    return {
        record_name: sorted(matches, key=lambda item: (item.source, str(item.path)))
        for record_name, matches in merged.items()
    }


def filter_unmatched_records_by_date(
    target_names_by_date: dict[str, set[str]],
    matched_index: dict[str, list[RawMatch]],
) -> dict[str, set[str]]:
    unmatched_by_date: dict[str, set[str]] = {}
    for record_date, target_names in target_names_by_date.items():
        unmatched_names = {
            record_name for record_name in target_names if record_name not in matched_index
        }
        if unmatched_names:
            unmatched_by_date[record_date] = unmatched_names
    return unmatched_by_date


def extract_date_vehicle(raw_path: Path, raw_root: Path) -> tuple[str | None, str | None]:
    try:
        relative_parts = raw_path.relative_to(raw_root).parts
    except ValueError:
        relative_parts = raw_path.parts

    for index, part in enumerate(relative_parts[:-1]):
        if DATE_DIR_RE.fullmatch(part) and index + 1 < len(relative_parts):
            return part, relative_parts[index + 1]

    return None, None


def extract_road_test_year_vehicle(
    raw_path: Path, road_test_root: Path
) -> tuple[str | None, str | None]:
    try:
        relative_parts = raw_path.relative_to(road_test_root).parts
    except ValueError:
        relative_parts = raw_path.parts

    if len(relative_parts) >= 3:
        vehicle_id = relative_parts[0]
        year = relative_parts[1]
        if re.fullmatch(r"\d{4}", year):
            return year, vehicle_id

    return None, None


def find_version_file(raw_record_path: Path, version_filenames: list[str]) -> Path | None:
    raw_dir = raw_record_path.parent
    for filename in version_filenames:
        candidate = raw_dir / filename
        if candidate.is_file():
            return candidate
    return None


def read_version_info(version_path: Path | None) -> tuple[Any | None, str | None]:
    if version_path is None:
        return None, None

    try:
        text = version_path.read_text(encoding="utf-8").strip()
    except UnicodeDecodeError:
        try:
            text = version_path.read_text(encoding="gb18030").strip()
        except OSError as exc:
            return None, str(exc)
    except OSError as exc:
        return None, str(exc)

    return parse_mdrive_conf_info(text), None


def normalize_mdrive_conf_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return " ".join(str(item).strip() for item in value if str(item).strip())
    if value is None:
        return ""
    return str(value).strip()


def split_mdrive_conf_columns(line: str) -> list[str]:
    return [
        token.strip(TOKEN_STRIP_CHARS)
        for token in re.split(r"[\s,]+", line.strip())
        if token.strip(TOKEN_STRIP_CHARS)
    ]


def parse_mdrive_conf_from_line(line: str) -> dict[str, str] | None:
    columns = split_mdrive_conf_columns(line)
    if not columns:
        return None

    try:
        conf_index = columns.index("mdrive_conf")
    except ValueError:
        return None

    if conf_index + 1 >= len(columns):
        return {"pakage": "mdrive_conf"}

    result = {
        "pakage": "mdrive_conf",
    }
    if conf_index + 2 < len(columns):
        result["branch"] = columns[conf_index + 2]
    result["version"] = columns[conf_index + 1]
    return result


def parse_mdrive_conf_info(text: str) -> dict[str, str] | None:
    if not text:
        return None

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None

    if isinstance(payload, dict):
        candidates = []
        if "mdrive_conf" in payload:
            candidates.append(f"mdrive_conf {normalize_mdrive_conf_text(payload['mdrive_conf'])}")
        candidates.extend(
            f"{key} {normalize_mdrive_conf_text(value)}"
            for key, value in payload.items()
            if key == "mdrive_conf"
            or "mdrive_conf" in key
            or "mdrive_conf" in normalize_mdrive_conf_text(value)
        )
        for candidate in candidates:
            parsed = parse_mdrive_conf_from_line(candidate)
            if parsed:
                return parsed
    elif isinstance(payload, list):
        for item in payload:
            parsed = parse_mdrive_conf_from_line(normalize_mdrive_conf_text(item))
            if parsed:
                return parsed

    for line in text.splitlines():
        if "mdrive_conf" not in line:
            continue
        parsed = parse_mdrive_conf_from_line(line)
        if parsed:
            return parsed

    return None


def build_candidate(
    raw_match: RawMatch,
    version_filenames: list[str],
    include_version_content: bool,
    version_cache: dict[Path, tuple[Any | None, str | None]],
) -> dict[str, Any]:
    raw_path = raw_match.path
    if raw_match.source == ROAD_TEST_SOURCE:
        year, vehicle_id = extract_road_test_year_vehicle(raw_path, raw_match.source_root)
        date = extract_record_date(raw_path.name)
    else:
        date, vehicle_id = extract_date_vehicle(raw_path, raw_match.source_root)
        year = date[:4] if date else None

    version_path = find_version_file(raw_path, version_filenames)

    candidate: dict[str, Any] = {
        "source": raw_match.source,
        "raw_record_path": path_for_json(raw_path),
        "raw_dir": path_for_json(raw_path.parent),
        "date": date,
        "year": year,
        "vehicle_id": vehicle_id,
        "version_path": path_for_json(version_path) if version_path else None,
    }

    if include_version_content:
        if version_path is None:
            candidate["version_info"] = None
        else:
            if version_path not in version_cache:
                version_cache[version_path] = read_version_info(version_path)
            version_info, version_error = version_cache[version_path]
            candidate["version_info"] = version_info
            if version_error:
                candidate["version_error"] = version_error

    return candidate


def build_report(
    case_root: Path,
    raw_root: Path,
    road_test_root: Path,
    soc_name: str,
    record_regex: str,
    case_records: list[Path],
    raw_index: dict[str, list[RawMatch]],
    version_filenames: list[str],
    include_version_content: bool,
    scan_errors: list[dict[str, str]],
    raw_search_dates: list[str] | None = None,
    undated_record_count: int = 0,
    exclude_dirs: list[str] | None = None,
) -> dict[str, Any]:
    vehicles: dict[str, list[dict[str, Any]]] = defaultdict(list)
    not_found: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    version_cache: dict[Path, tuple[Any | None, str | None]] = {}

    for case_path in case_records:
        record_name = case_path.name
        raw_paths = raw_index.get(record_name, [])
        if not raw_paths:
            status = "raw_not_found"
        elif len(raw_paths) == 1:
            status = "matched"
        else:
            status = "ambiguous"

        status_counts[status] += 1
        candidates = [
            build_candidate(
                raw_match,
                version_filenames,
                include_version_content,
                version_cache,
            )
            for raw_match in raw_paths
        ]

        if not candidates:
            not_found.append(
                {
                    "case_record_path": path_for_json(case_path),
                }
            )
            continue

        for candidate in candidates:
            vehicle_key = candidate.get("vehicle_id") or "UNKNOWN"
            vehicles[vehicle_key].append(
                {
                    "case_record_path": path_for_json(case_path),
                    "raw_record_path": candidate["raw_record_path"],
                    "version_path": candidate["version_path"],
                    "version_info": candidate.get("version_info"),
                    "match_status": status,
                }
            )

    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "case_root": path_for_json(case_root),
        "raw_root": path_for_json(raw_root),
        "road_test_root": path_for_json(road_test_root),
        "soc": soc_name,
        "record_regex": record_regex,
        "version_filenames": version_filenames,
        "exclude_dirs": exclude_dirs or [],
        "summary": {
            "case_record_count": len(case_records),
            "matched_count": status_counts["matched"],
            "ambiguous_count": status_counts["ambiguous"],
            "raw_not_found_count": status_counts["raw_not_found"],
            "vehicle_count": len(vehicles),
            "raw_search_date_count": len(raw_search_dates or []),
            "undated_record_count": undated_record_count,
            "scan_error_count": len(scan_errors),
        },
        "vehicles": dict(sorted(vehicles.items())),
        "NotFound": not_found,
    }


def write_json(output_path: Path, report: dict[str, Any]) -> None:
    if output_path.parent != Path("."):
        output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    version_filenames = args.version_filenames or list(DEFAULT_VERSION_FILENAMES)
    exclude_dirs = set(args.exclude_dir)
    progress = ProgressLogger(not args.quiet)

    try:
        record_re = compile_record_regex(args.record_regex)
        require_dir(args.case_root, "--case-root")
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    scan_errors: list[dict[str, str]] = []
    case_records = scan_case_records(
        args.case_root,
        args.soc,
        record_re,
        args.follow_links,
        scan_errors,
        exclude_dirs,
        progress,
        args.progress_interval,
    )
    target_names = {path.name for path in case_records}
    target_names_by_date, undated_names = group_record_names_by_date(target_names)
    if undated_names:
        progress(
            f"records without leading YYYYMMDD will not be searched in raw: count={len(undated_names)}"
        )
    progress(
        f"raw same-day search plan: unique_records={len(target_names)}, "
        f"date_dirs={len(target_names_by_date)}"
    )
    raw_index_same_day = scan_raw_records(
        args.raw_root,
        target_names_by_date,
        args.follow_links,
        scan_errors,
        progress,
        args.progress_interval,
    )
    next_day_targets_by_record_date = filter_unmatched_records_by_date(
        target_names_by_date, raw_index_same_day
    )
    next_day_targets_by_search_date = shift_record_names_to_next_day(
        next_day_targets_by_record_date
    )
    progress(
        "raw next-day fallback plan: "
        f"records={sum(len(names) for names in next_day_targets_by_search_date.values())}, "
        f"date_dirs={len(next_day_targets_by_search_date)}"
    )
    raw_index_next_day = scan_raw_records(
        args.raw_root,
        next_day_targets_by_search_date,
        args.follow_links,
        scan_errors,
        progress,
        args.progress_interval,
    )
    raw_index_00 = merge_raw_indexes(raw_index_same_day, raw_index_next_day)
    road_test_targets_by_date = filter_unmatched_records_by_date(
        target_names_by_date, raw_index_00
    )
    progress(
        "road-test fallback plan: "
        f"records={sum(len(names) for names in road_test_targets_by_date.values())}, "
        f"date_dirs={len(road_test_targets_by_date)}"
    )
    raw_index_road_test = scan_road_test_records(
        args.road_test_root,
        road_test_targets_by_date,
        args.follow_links,
        scan_errors,
        progress,
        args.progress_interval,
    )
    raw_index = merge_raw_indexes(raw_index_00, raw_index_road_test)
    progress("building vehicle grouped JSON report")

    report = build_report(
        args.case_root,
        args.raw_root,
        args.road_test_root,
        args.soc,
        args.record_regex,
        case_records,
        raw_index,
        version_filenames,
        not args.no_version_content,
        scan_errors,
        sorted(set(target_names_by_date) | set(next_day_targets_by_search_date)),
        len(undated_names),
        sorted(exclude_dirs),
    )
    write_json(args.output, report)
    progress(f"JSON written: {args.output}")

    summary = report["summary"]
    print(
        "wrote {output} | records={records} matched={matched} "
        "ambiguous={ambiguous} raw_not_found={missing} vehicles={vehicles}".format(
            output=args.output,
            records=summary["case_record_count"],
            matched=summary["matched_count"],
            ambiguous=summary["ambiguous_count"],
            missing=summary["raw_not_found_count"],
            vehicles=summary["vehicle_count"],
        )
    )
    if summary["scan_error_count"]:
        print(f"scan errors: {summary['scan_error_count']}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
