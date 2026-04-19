import re
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Sequence, Tuple

from core.errors import FindRecordError, TagFileMissingError
from core.models import TaskEntry
from utils import parser

PathTextReader = Callable[[str], str]
RecordIndex = Dict[int, List[Tuple[int, Path]]]
_TAG_LINE_RE = re.compile(r'msg:\ "([^"]+)"')
_TAG_TIME_RE = re.compile(
    r"([0-9]{4})/([0-9]{1,2})/([0-9]{1,2}) ([0-9]{1,2}):([0-9]{2}):([0-9]{2})"
)
_TAG_TIME_AM_PM_RE = re.compile(
    r"([0-9]{1,2})/([0-9]{1,2})/([0-9]{4}), ([0-9]{1,2}):([0-9]{2}):([0-9]{2}) (AM|PM)"
)


def parse_tag_message(message: str) -> Tuple[str, datetime]:
    """解析 tag 文本中的名称和时间，兼容 shell 里的两种时间格式。"""
    tag_name = message.split(" :", 1)[0].strip()
    matched_direct = _TAG_TIME_RE.search(message)
    if matched_direct is not None:
        year, month, day, hour, minute, second = matched_direct.groups()
        return tag_name, datetime(
            int(year),
            int(month),
            int(day),
            int(hour),
            int(minute),
            int(second),
        )
    matched_am_pm = _TAG_TIME_AM_PM_RE.search(message)
    if matched_am_pm is None:
        raise ValueError("无法解析 tag 时间: {0}".format(message))
    month, day, year, hour, minute, second, am_pm = matched_am_pm.groups()
    hour_value = int(hour)
    if am_pm == "PM" and hour_value < 12:
        hour_value += 12
    elif am_pm == "AM" and hour_value == 12:
        hour_value = 0
    return tag_name, datetime(
        int(year),
        int(month),
        int(day),
        hour_value,
        int(minute),
        int(second),
    )


def build_record_index(record_paths: Sequence[Path]) -> RecordIndex:
    """按分钟桶建立 record 索引，保留秒级偏移用于后续窗口匹配。"""
    records_by_minute = {}
    for record_path in record_paths:
        record_time = record_path.name.split(".")[-1]
        if not re.fullmatch(r"[0-9]{6}", record_time):
            continue
        hour = int(record_time[0:2])
        minute = int(record_time[2:4])
        second = int(record_time[4:6])
        total_seconds = hour * 3600 + minute * 60 + second
        minute_key = hour * 60 + minute
        records_by_minute.setdefault(minute_key, []).append(
            (total_seconds, record_path)
        )
    return records_by_minute


def select_matching_record_paths(
    records_by_minute: RecordIndex,
    tag_time: datetime,
    before: int,
    after: int,
) -> List[Path]:
    """按 shell 当前规则匹配窗口前补文件和窗口内文件。"""
    tag_seconds = tag_time.hour * 3600 + tag_time.minute * 60 + tag_time.second
    start_sec = tag_seconds - before
    end_sec = tag_seconds + after
    start_min = (start_sec - 60) // 60
    end_min = end_sec // 60
    candidate_records = []
    for minute_key in range(start_min, end_min + 1):
        candidate_records.extend(records_by_minute.get(minute_key, []))
    sorted_candidates = sorted(
        candidate_records,
        key=lambda item: (item[0], item[1].name),
    )
    final_paths = []
    last_before_by_soc = {}
    for record_second, record_path in sorted_candidates:
        if record_second >= end_sec:
            continue
        soc_name = _detect_soc_name(record_path)
        if record_second >= start_sec:
            final_paths.append(record_path)
            continue
        last_before_by_soc[soc_name] = (record_second, record_path)
    prefix_paths = [
        record_path
        for _, record_path in sorted(
            last_before_by_soc.values(),
            key=lambda item: (item[0], item[1].name),
        )
    ]
    return prefix_paths + final_paths


def find_local_tasks(
    data_root: Path,
    target_date: str,
    before: int,
    after: int,
    soc_filter: str = "",
) -> List[TaskEntry]:
    """扫描本地或 NAS 目录并按现有 shell 规则构造查询任务。"""
    path_texts = [
        str(path_obj)
        for path_obj in data_root.rglob("*")
        if path_obj.is_file()
    ]
    return find_tasks_from_path_texts(
        path_texts,
        _read_local_text,
        target_date=target_date,
        before=before,
        after=after,
        soc_filter=soc_filter,
        source_root=str(data_root),
    )


def find_tasks_from_path_texts(
    path_texts: Sequence[str],
    read_text: PathTextReader,
    target_date: str,
    before: int,
    after: int,
    soc_filter: str = "",
    source_root: str = "",
) -> List[TaskEntry]:
    """基于给定路径列表和内容读取器构造查询任务，支持本地和远程来源。"""
    source_label = source_root or "查询根目录"
    related_paths = []
    record_paths = []
    tag_paths = []
    for path_text in path_texts:
        path_obj = Path(path_text)
        if _is_record_candidate(path_obj, target_date, soc_filter):
            record_paths.append(path_obj)
            related_paths.append(path_text)
            continue
        if _is_tag_candidate(path_obj, target_date):
            tag_paths.append(path_text)
            related_paths.append(path_text)
    if not related_paths:
        raise FindRecordError(
            "{0} 目录下找不到相关的文件！".format(source_label)
        )
    if not tag_paths:
        raise TagFileMissingError(
            "{0} 找不到对应的 tag 文件！".format(source_label)
        )
    records_by_minute = build_record_index(record_paths)
    task_entries = []
    for tag_path in sorted(tag_paths):
        tag_messages = _load_tag_messages_from_text(read_text(tag_path))
        for tag_message in tag_messages:
            tag_name, tag_time = parse_tag_message(tag_message)
            matched_paths = select_matching_record_paths(
                records_by_minute,
                tag_time,
                before,
                after,
            )
            task_entries.append(
                TaskEntry.from_manifest_parts(
                    time=tag_time.strftime("%Y-%m-%d %H:%M:%S"),
                    name=parser.sanitize_name(tag_name),
                    paths=[str(path_obj) for path_obj in matched_paths],
                )
            )
    task_entries.sort(key=lambda task_entry: task_entry.time)
    if not task_entries:
        raise FindRecordError("未找到到任何有效 record")
    for index, task_entry in enumerate(task_entries, 1):
        task_entry.assign_id(index)
    return task_entries


def dump_manifest(task_entries: Sequence[TaskEntry], manifest_path: Path) -> str:
    """按既有 manifest 格式写出查询结果。"""
    manifest_lines = [
        "{0}|{1}|{2}".format(
            task_entry.time,
            task_entry.name,
            " ".join(task_entry.paths),
        )
        for task_entry in task_entries
    ]
    manifest_text = "\n".join(manifest_lines)
    manifest_path.write_text(manifest_text, encoding="utf-8")
    return manifest_text


def _is_record_candidate(
    path_obj: Path,
    target_date: str,
    soc_filter: str,
) -> bool:
    if soc_filter and soc_filter not in str(path_obj):
        return False
    file_name = path_obj.name
    return file_name.startswith(target_date) and "record" in file_name


def _is_tag_candidate(path_obj: Path, target_date: str) -> bool:
    file_name = path_obj.name
    return "tag" in file_name and target_date in file_name


def _load_tag_messages_from_text(tag_content: str) -> List[str]:
    tag_messages = []
    for line in tag_content.splitlines():
        matched_line = _TAG_LINE_RE.search(line)
        if matched_line is None:
            continue
        tag_messages.append(matched_line.group(1).replace("\\n", ""))
    return tag_messages


def _read_local_text(path_text: str) -> str:
    return Path(path_text).read_text(encoding="utf-8")


def _detect_soc_name(record_path: Path) -> str:
    path_text = str(record_path)
    if "soc1" in path_text:
        return "soc1"
    if "soc2" in path_text:
        return "soc2"
    return "unknown"


class RecordFinderManager:
    """负责按既有规则解析 tag 并匹配 record 查询结果。"""

    def parse_tag_message(self, message: str) -> Tuple[str, datetime]:
        """解析单条 tag 消息中的名称和时间。"""
        return parse_tag_message(message)

    def build_record_index(
        self,
        record_paths: Sequence[Path],
    ) -> RecordIndex:
        """按分钟桶构建 record 索引。"""
        return build_record_index(record_paths)

    def select_matching_record_paths(
        self,
        records_by_minute: RecordIndex,
        tag_time: datetime,
        before: int,
        after: int,
    ) -> List[Path]:
        """根据时间窗从索引中筛出匹配的 record 路径。"""
        return select_matching_record_paths(records_by_minute, tag_time, before, after)

    def find_local_tasks(
        self,
        data_root: Path,
        target_date: str,
        before: int,
        after: int,
        soc_filter: str = "",
    ) -> List[TaskEntry]:
        """扫描本地或 NAS 根目录并返回查询任务。"""
        return find_local_tasks(
            data_root,
            target_date=target_date,
            before=before,
            after=after,
            soc_filter=soc_filter,
        )

    def find_tasks_from_path_texts(
        self,
        path_texts: Sequence[str],
        read_text: PathTextReader,
        target_date: str,
        before: int,
        after: int,
        soc_filter: str = "",
        source_root: str = "",
    ) -> List[TaskEntry]:
        """基于路径列表和文本读取器构造查询任务。"""
        return find_tasks_from_path_texts(
            path_texts,
            read_text,
            target_date=target_date,
            before=before,
            after=after,
            soc_filter=soc_filter,
            source_root=source_root,
        )

    def dump_manifest(
        self,
        task_entries: Sequence[TaskEntry],
        manifest_path: Path,
    ) -> str:
        """按既有格式写出 manifest 文件。"""
        return dump_manifest(task_entries, manifest_path)
