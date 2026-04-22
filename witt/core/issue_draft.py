from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import re
from typing import List, Union

SUGGESTED_TITLE_TEMPLATE = "[车型-模块-车号]问题简述"
DEFAULT_ISSUE_DESCRIPTION = "填写补充描述"
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
    issue_description: str = DEFAULT_ISSUE_DESCRIPTION


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
start(-s): {issue_draft.playback_range_text}
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
    issue_path = work_dir / "issues" / "issue_{0}.md".format(timestamp_text)
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


def build_issue_title_from_vmc(
    vmc_path: Union[str, Path],
    tag_text: str,
) -> str:
    """从 vmc.sh 读取车型和车号，生成 issue 建议标题。"""
    if not vmc_path:
        return SUGGESTED_TITLE_TEMPLATE
    try:
        vmc_text = Path(vmc_path).read_text(encoding="utf-8")
    except (OSError, TypeError, ValueError):
        return SUGGESTED_TITLE_TEMPLATE
    vehicle_model = _extract_vmc_value(vmc_text, "MDRIVE_VEHICLE_MODEL")
    vehicle_name = _extract_vmc_value(vmc_text, "MDRIVE_VEHICLE_NAME")
    if not vehicle_model or not vehicle_name or not tag_text:
        return SUGGESTED_TITLE_TEMPLATE
    vehicle_model = vehicle_model.split("_", 1)[0]
    return "[{0}-模块-{1}]{2}".format(vehicle_model, vehicle_name, tag_text)


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


def _extract_vmc_value(vmc_text: str, key_name: str) -> str:
    """从 vmc.sh 文本中提取指定环境变量值。"""
    matched_value = re.search(
        r"^{0}=(.*)$".format(key_name),
        vmc_text,
        flags=re.MULTILINE,
    )
    if matched_value is None:
        return ""
    return matched_value.group(1).strip().strip('"')


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
    path_parts = [
        part
        for part in path_obj.parts
        if part and part != path_obj.anchor
    ]
    if target_date in path_parts and vehicle in path_parts:
        suffix_parts = path_parts[
            max(path_parts.index(target_date), path_parts.index(vehicle)) + 1 :
        ]
        if suffix_parts:
            return suffix_parts
    try:
        relative_path = path_obj.relative_to(DEFAULT_LOCAL_RAW_PREFIX)
    except ValueError:
        return []
    return [
        part
        for part in relative_path.parts
        if part and part != relative_path.anchor
    ]
