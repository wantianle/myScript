import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Union


@dataclass
class IssueDraft:
    tag_text: str
    vehicle: str
    target_date: str
    playback_command: str
    data_path_text: str
    version_text: str = ""
    playback_rate: float = 1.0
    playback_range_text: str = "全播"
    playback_channels: List[str] = field(default_factory=list)
    issue_description: str = "填写补充描述"
    expected_result: str = "填写正确情况"


def build_issue_filename(issue_timestamp: str, issue_name: str = "") -> str:
    """根据时间戳和预留名称生成 issue 文件名。"""
    suffix = _normalize_issue_name(issue_name) or issue_timestamp
    return "issue_{0}.md".format(suffix)


def build_issue_path(
    work_dir: Path,
    issue_timestamp: str,
    issue_name: str = "",
) -> Path:
    """构造 issue 草稿文件路径。"""
    return work_dir / "issues" / build_issue_filename(issue_timestamp, issue_name)


def build_issue_data_path_text(
    path_texts: List[str],
    target_date: str,
    vehicle: str,
    issue_root: Union[str, Path] = "/media/nas/00.raw",
) -> str:
    """按日期和车号截断原始路径，统一映射到 issue 展示路径。"""
    return "\n".join(
        [
            _format_issue_data_path(path_text, target_date, vehicle, issue_root)
            for path_text in path_texts
        ]
    )


def render_issue_markdown(issue_draft: IssueDraft) -> str:
    """渲染 issue 草稿 Markdown 内容。"""
    version_block = issue_draft.version_text or "未提供版本文件"
    channels_text = ", ".join(issue_draft.playback_channels) if issue_draft.playback_channels else "无"
    return f"""- **tag：** {issue_draft.tag_text}
- **车辆日期：** {issue_draft.vehicle} | {issue_draft.target_date}
- **问题描述：**
> {issue_draft.issue_description}
- **预期结果：**
> {issue_draft.expected_result}
- **车辆软硬件信息：**
```json
{version_block}
```
- **数据路径：**
```bash
{issue_draft.data_path_text}
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
    issue_name: str = "",
    issue_timestamp: Union[str, datetime] = "",
) -> Path:
    """保存 issue 草稿到 work_dir/issues。"""
    timestamp_text = _normalize_issue_timestamp(issue_timestamp)
    if not timestamp_text:
        timestamp_text = datetime.now().strftime("%Y%m%d_%H%M%S")
    issue_path = build_issue_path(work_dir, timestamp_text, issue_name)
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


def _normalize_issue_name(issue_name: str) -> str:
    """清理预留 issue 名称，便于后续改成中文 tag 或自定义标题。"""
    cleaned_name = issue_name.strip().replace("/", "_").replace("\\", "_")
    return re.sub(r"\s+", "_", cleaned_name)


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


def _format_issue_data_path(
    path_text: str,
    target_date: str,
    vehicle: str,
    issue_root: Union[str, Path],
) -> str:
    """将路径从日期和车号开始截断，并挂到统一 issue 根目录。"""
    path_parts = Path(path_text).parts
    start_index = _find_issue_path_start(path_parts, target_date, vehicle)
    if start_index < 0:
        return path_text
    return str(Path(issue_root).joinpath(*path_parts[start_index:]))


def _find_issue_path_start(
    path_parts: tuple,
    target_date: str,
    vehicle: str,
) -> int:
    """寻找日期与车号连续出现的位置。"""
    for index in range(len(path_parts) - 1):
        if path_parts[index] == target_date and path_parts[index + 1] == vehicle:
            return index
    return -1
