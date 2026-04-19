from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Union

SUGGESTED_TITLE_TEMPLATE = "[车型-模块-车号]问题简述"
DEFAULT_LOCAL_RAW_PREFIX = Path("/media/mini/data/data")


@dataclass
class ReplayIssueMarker:
    playback_start_sec: int
    issue_description: str


@dataclass
class IssueDraft:
    tag_text: str
    vehicle: str
    target_date: str
    playback_command: str
    version_text: str = ""
    playback_rate: float = 1.0
    playback_range_text: str = "全播"
    playback_channels: List[str] = field(default_factory=list)
    suggested_title: str = SUGGESTED_TITLE_TEMPLATE
    issue_description: str = "填写补充描述"


def build_issue_filename(issue_timestamp: str) -> str:
    """根据时间戳生成 issue 文件名。"""
    return "issue_{0}.md".format(issue_timestamp)


def build_issue_path(
    work_dir: Path,
    issue_timestamp: str,
) -> Path:
    """构造 issue 草稿文件路径。"""
    return work_dir / "issues" / build_issue_filename(issue_timestamp)


def render_issue_markdown(issue_draft: IssueDraft) -> str:
    """渲染 issue 草稿 Markdown 内容。"""
    version_block = issue_draft.version_text or "未提供版本文件"
    channels_text = ", ".join(issue_draft.playback_channels) if issue_draft.playback_channels else "无"
    return f"""- **建议标题：** {issue_draft.suggested_title}
- **tag：** {issue_draft.tag_text}
- **车辆/日期：** {issue_draft.vehicle} | {issue_draft.target_date}
- **问题和预期描述：**
> {issue_draft.issue_description}
- **车辆软硬件信息：**
```json
{version_block}
```
- **回播命令：**
```bash
{issue_draft.playback_command}
```
- **回播参数：**
```text
range(-s): {issue_draft.playback_range_text}
rate(-r): x{issue_draft.playback_rate:g}
channels(-k): {channels_text}
```
"""


def save_issue_draft(
    work_dir: Path,
    issue_draft: IssueDraft,
    issue_timestamp: Union[str, datetime] = "",
) -> Path:
    """保存 issue 草稿到 work_dir/issues。"""
    timestamp_text = _normalize_issue_timestamp(issue_timestamp)
    if not timestamp_text:
        timestamp_text = datetime.now().strftime("%Y%m%d_%H%M%S")
    issue_path = build_issue_path(work_dir, timestamp_text)
    issue_path.parent.mkdir(parents=True, exist_ok=True)
    issue_path.write_text(render_issue_markdown(issue_draft), encoding="utf-8")
    return issue_path


def load_version_text(version_source: Union[str, Path]) -> str:
    """读取版本文件内容，失败时返回可读占位信息。"""
    if not version_source:
        return ""
    version_path = Path(version_source)
    try:
        return version_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, TypeError, ValueError):
        return str(version_source)


def _normalize_issue_timestamp(issue_timestamp: Union[str, datetime]) -> str:
    """将原始时间文本规范化为 issue 文件名时间戳。"""
    if isinstance(issue_timestamp, datetime):
        return issue_timestamp.strftime("%Y%m%d_%H%M%S")
    timestamp_text = str(issue_timestamp).strip()
    if not timestamp_text:
        return ""
    for time_format in (
        "%Y%m%d_%H%M%S",
        "%Y%m%d%H%M%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(timestamp_text, time_format).strftime("%Y%m%d_%H%M%S")
        except ValueError:
            continue
    return timestamp_text


def format_issue_data_path(
    path_text: str,
    target_date: str,
    vehicle: str,
    issue_root: Union[str, Path],
) -> str:
    """统一映射 issue 数据路径到 NAS 根目录。"""
    issue_relative_parts = _build_issue_relative_parts(
        Path(path_text),
        target_date,
        vehicle,
    )
    if not issue_relative_parts:
        raise ValueError(
            "无法根据原始路径推断准确 NAS 路径: {0}".format(path_text)
        )
    return str(
        Path(issue_root).joinpath(
            target_date,
            vehicle,
            *issue_relative_parts,
        )
    )


def _build_issue_relative_parts(
    path_obj: Path,
    target_date: str,
    vehicle: str,
) -> List[str]:
    """从原始路径中提取挂到日期/车号后的相对路径。"""
    path_parts = _normalize_issue_path_parts(path_obj)
    suffix_start = _find_issue_suffix_start(path_parts, target_date, vehicle)
    if suffix_start >= 0:
        suffix_parts = list(path_parts[suffix_start:])
        if suffix_parts:
            return suffix_parts
    local_suffix_parts = _extract_local_raw_suffix_parts(path_obj)
    if local_suffix_parts is not None:
        return local_suffix_parts
    return []


def _normalize_issue_path_parts(path_obj: Path) -> tuple:
    """移除根锚点，便于统一处理路径段。"""
    anchor = path_obj.anchor
    return tuple(
        part
        for part in path_obj.parts
        if part and part != anchor
    )


def _find_issue_suffix_start(
    path_parts: tuple,
    target_date: str,
    vehicle: str,
) -> int:
    """寻找日期/车号之后的相对路径起点。"""
    date_index = _find_path_part(path_parts, target_date)
    vehicle_index = _find_path_part(path_parts, vehicle)
    if date_index >= 0 and vehicle_index >= 0:
        return max(date_index, vehicle_index) + 1
    return -1


def _find_path_part(path_parts: tuple, expected: str) -> int:
    """返回指定路径段首次出现的位置。"""
    for index, path_part in enumerate(path_parts):
        if path_part == expected:
            return index
    return -1


def _extract_local_raw_suffix_parts(path_obj: Path) -> Optional[List[str]]:
    """识别默认本地原始数据目录并保留其后缀路径。"""
    try:
        relative_path = path_obj.relative_to(DEFAULT_LOCAL_RAW_PREFIX)
    except ValueError:
        return None
    suffix_parts = list(_normalize_issue_path_parts(relative_path))
    return suffix_parts or None
