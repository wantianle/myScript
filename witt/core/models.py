from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, TypedDict, Union


class RawLogicConfig(TypedDict, total=False):
    vehicle: str
    target_date: str
    mode: Union[int, str]
    version: Union[str, Path]
    soc: str
    before: Union[int, str]
    after: Union[int, str]
    blacklist: Union[List[str], str]


class RawHostConfig(TypedDict, total=False):
    mdrive_root: str
    nas_root: str
    data_root: str
    dest_root: str


class RawRemoteConfig(TypedDict, total=False):
    user: str
    ip: str
    data_root: str


class RawDockerConfig(TypedDict, total=False):
    container: str
    host_mount: str
    docker_mount: str
    docker_scripts: str
    setup_env: str


class RawPathsConfig(TypedDict, total=False):
    scripts_dir: str


class RawAppConfig(TypedDict):
    host: RawHostConfig
    remote: RawRemoteConfig
    docker: RawDockerConfig
    paths: RawPathsConfig
    logic: RawLogicConfig


class RawReplayRecord(TypedDict):
    path: str
    begin: Union[str, datetime]
    duration: int


class RawReplayHistoryEntry(TypedDict, total=False):
    created_at: str
    source_type: str
    replay_mode: str
    selection_label: str
    display_tag: str
    issue_timestamp: str
    vehicle: str
    target_date: str
    records: List[RawReplayRecord]
    start_sec: int
    end_sec: int
    playback_rate: float
    channel_filters: List[str]


class RawLibraryEntry(TypedDict, total=False):
    tag: str
    time: str
    last_update: Dict[str, str]
    socs: Dict[str, List[RawReplayRecord]]


class RawRecordMeta(TypedDict, total=False):
    tag_info: Dict[str, Union[str, int]]
    vehicle: str
    date: str
    last_update: Dict[str, str]
    files: Dict[str, List[str]]


@dataclass
class TaskEntry:
    time: str
    name: str
    soc_paths: Dict[str, List[str]]
    paths: List[str]
    id: str = field(default="")

    @classmethod
    def from_record_paths(
        cls,
        time: str,
        name: str,
        paths: Sequence[str],
    ) -> "TaskEntry":
        soc_paths = {"soc1": [], "soc2": []}
        for path_text in paths:
            if "soc1" in path_text:
                soc_paths["soc1"].append(path_text)
            elif "soc2" in path_text:
                soc_paths["soc2"].append(path_text)
        return cls(
            time=time,
            name=name,
            soc_paths=soc_paths,
            paths=list(paths),
        )

    def assign_id(self, index: int) -> None:
        """根据排序后的序号为任务分配稳定 ID。"""
        self.id = f"{index:02d}"


@dataclass
class LogicConfig:
    vehicle: str
    target_date: str
    mode: int
    version: Union[str, Path]
    soc: str
    before: int
    after: int
    blacklist: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw_logic: RawLogicConfig) -> "LogicConfig":
        raw_blacklist = raw_logic.get("blacklist")
        if isinstance(raw_blacklist, list):
            blacklist = [str(item) for item in raw_blacklist]
        elif raw_blacklist:
            blacklist = [str(raw_blacklist)]
        else:
            blacklist = []
        raw_version = raw_logic.get("version", "") or ""
        version = raw_version if isinstance(raw_version, Path) else str(raw_version)
        return cls(
            vehicle=str(raw_logic.get("vehicle", "")),
            target_date=str(raw_logic.get("target_date", "")),
            mode=int(raw_logic.get("mode", 0)),
            version=version,
            soc=str(raw_logic.get("soc", "")),
            before=int(raw_logic.get("before", 0)),
            after=int(raw_logic.get("after", 0)),
            blacklist=blacklist,
        )


@dataclass
class HostConfig:
    mdrive_root: str
    nas_root: str
    data_root: str
    dest_root: str

    @classmethod
    def from_dict(cls, raw_host: RawHostConfig) -> "HostConfig":
        return cls(
            mdrive_root=str(raw_host.get("mdrive_root", "")),
            nas_root=str(raw_host.get("nas_root", "")),
            data_root=str(raw_host.get("data_root", "")),
            dest_root=str(raw_host.get("dest_root", "")),
        )


@dataclass
class RemoteConfig:
    user: str
    ip: str
    data_root: str

    @classmethod
    def from_dict(cls, raw_remote: RawRemoteConfig) -> "RemoteConfig":
        return cls(
            user=str(raw_remote.get("user", "")),
            ip=str(raw_remote.get("ip", "")),
            data_root=str(raw_remote.get("data_root", "")),
        )


@dataclass
class DockerConfig:
    container: str
    host_mount: str
    docker_mount: str
    docker_scripts: str
    setup_env: str

    @classmethod
    def from_dict(cls, raw_docker: RawDockerConfig) -> "DockerConfig":
        return cls(
            container=str(raw_docker.get("container", "")),
            host_mount=str(raw_docker.get("host_mount", "")),
            docker_mount=str(raw_docker.get("docker_mount", "")),
            docker_scripts=str(raw_docker.get("docker_scripts", "")),
            setup_env=str(raw_docker.get("setup_env", "")),
        )


@dataclass
class PathsConfig:
    scripts_dir: str

    @classmethod
    def from_dict(cls, raw_paths: RawPathsConfig) -> "PathsConfig":
        return cls(
            scripts_dir=str(raw_paths.get("scripts_dir", "")),
        )


@dataclass
class AppConfig:
    host: HostConfig
    remote: RemoteConfig
    docker: DockerConfig
    paths: PathsConfig
    logic: LogicConfig

    @classmethod
    def from_dict(cls, raw_config: RawAppConfig) -> "AppConfig":
        return cls(
            host=HostConfig.from_dict(raw_config["host"]),
            remote=RemoteConfig.from_dict(raw_config["remote"]),
            docker=DockerConfig.from_dict(raw_config["docker"]),
            paths=PathsConfig.from_dict(raw_config["paths"]),
            logic=LogicConfig.from_dict(raw_config["logic"]),
        )


@dataclass
class ReplayRecord:
    path: str
    begin: Union[str, datetime]
    duration: int

    @classmethod
    def from_cache_dict(cls, raw_record: RawReplayRecord) -> "ReplayRecord":
        return cls(
            path=str(raw_record["path"]),
            begin=raw_record["begin"],
            duration=int(raw_record["duration"]),
        )

    def to_cache_dict(self) -> RawReplayRecord:
        begin_value = self.begin.isoformat() if isinstance(self.begin, datetime) else str(self.begin)
        return {
            "path": self.path,
            "begin": begin_value,
            "duration": self.duration,
        }


@dataclass
class ReplayHistoryEntry:
    created_at: str
    source_type: str
    replay_mode: str
    display_tag: str
    issue_timestamp: str
    vehicle: str
    target_date: str
    selection_label: str = ""
    records: List[ReplayRecord] = field(default_factory=list)
    start_sec: int = 0
    end_sec: int = 0
    playback_rate: float = 1.0
    channel_filters: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw_entry: RawReplayHistoryEntry) -> "ReplayHistoryEntry":
        return cls(
            created_at=str(raw_entry.get("created_at", "")),
            source_type=str(raw_entry.get("source_type", "")),
            replay_mode=str(raw_entry.get("replay_mode", "")),
            selection_label=str(raw_entry.get("selection_label", "")),
            display_tag=str(raw_entry.get("display_tag", "")),
            issue_timestamp=str(raw_entry.get("issue_timestamp", "")),
            vehicle=str(raw_entry.get("vehicle", "")),
            target_date=str(raw_entry.get("target_date", "")),
            records=[
                ReplayRecord.from_cache_dict(raw_record)
                for raw_record in raw_entry.get("records", [])
            ],
            start_sec=int(raw_entry.get("start_sec", 0)),
            end_sec=int(raw_entry.get("end_sec", 0)),
            playback_rate=float(raw_entry.get("playback_rate", 1.0)),
            channel_filters=[
                str(channel_name)
                for channel_name in raw_entry.get("channel_filters", [])
            ],
        )

    @property
    def resolved_selection_label(self) -> str:
        """返回历史记录展示摘要，优先兼容旧数据中的显式字段。"""
        if self.selection_label:
            return self.selection_label
        return build_history_selection_label(
            self.records,
            self.display_tag,
            self.source_type,
        )

    def to_dict(self) -> RawReplayHistoryEntry:
        return {
            "created_at": self.created_at,
            "source_type": self.source_type,
            "replay_mode": self.replay_mode,
            "display_tag": self.display_tag,
            "issue_timestamp": self.issue_timestamp,
            "vehicle": self.vehicle,
            "target_date": self.target_date,
            "records": [
                replay_record.to_cache_dict()
                for replay_record in self.records
            ],
            "start_sec": self.start_sec,
            "end_sec": self.end_sec,
            "playback_rate": self.playback_rate,
            "channel_filters": self.channel_filters,
        }


def build_history_selection_label(
    records: Sequence[ReplayRecord],
    display_tag: str,
    source_type: str,
) -> str:
    """根据记录列表和来源生成稳定的历史摘要标题。"""
    if not records:
        return display_tag or source_type
    file_count = len(records)
    soc_names = sorted(
        {
            Path(replay_record.path).parent.name
            for replay_record in records
            if Path(replay_record.path).parent.name.startswith("soc")
        }
    )
    soc_text = ",".join(soc_names) if soc_names else "single"
    if source_type == "manual":
        return "manual | {0} | {1} files".format(
            Path(records[0].path).name,
            file_count,
        )
    return "{0} | {1} | {2} files".format(
        display_tag or Path(records[0].path).name,
        soc_text,
        file_count,
    )


@dataclass
class LibraryEntry:
    tag: str
    time: str
    socs: Dict[str, List[ReplayRecord]] = field(default_factory=dict)
    last_update: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_cache_dict(cls, raw_entry: RawLibraryEntry) -> "LibraryEntry":
        raw_tag = raw_entry.get("tag")
        raw_time = raw_entry.get("time")
        if raw_tag is None or raw_time is None:
            raise ValueError("library cache entry missing tag or time")
        return cls(
            tag=str(raw_tag),
            time=str(raw_time),
            last_update=dict(raw_entry.get("last_update") or {}),
            socs={
                soc_name: [
                    ReplayRecord.from_cache_dict(raw_record)
                    for raw_record in raw_records
                ]
                for soc_name, raw_records in raw_entry.get("socs", {}).items()
            },
        )

    def to_cache_dict(self) -> RawLibraryEntry:
        return {
            "tag": self.tag,
            "time": self.time,
            "last_update": self.last_update,
            "socs": {
                soc_name: [
                    replay_record.to_cache_dict()
                    for replay_record in replay_records
                ]
                for soc_name, replay_records in self.socs.items()
            },
        }

    @classmethod
    def from_record_meta(cls, record_meta: "RecordMeta", tag_dir: Path) -> "LibraryEntry":
        entry = cls(
            tag=record_meta.tag_info.name,
            time=record_meta.tag_info.time,
            last_update=dict(record_meta.last_update),
        )
        for soc_name in record_meta.files:
            replay_records = record_meta.build_soc_replay_records(tag_dir, soc_name)
            if replay_records:
                entry.socs[soc_name] = replay_records
        return entry


@dataclass
class ChannelInfo:
    name: str
    count: int


@dataclass
class TagInfo:
    name: str
    time: str
    offset_bf: int
    offset_af: int
    abs_start: str
    abs_end: str

    @classmethod
    def from_task_entry(
        cls,
        task_entry: TaskEntry,
        before: int,
        after: int,
    ) -> "TagInfo":
        task_datetime = datetime.strptime(task_entry.time, "%Y-%m-%d %H:%M:%S")
        return cls(
            name=task_entry.name,
            time=task_entry.time,
            offset_bf=before,
            offset_af=after,
            abs_start=(task_datetime - timedelta(seconds=before)).isoformat(),
            abs_end=(task_datetime + timedelta(seconds=after)).isoformat(),
        )


@dataclass
class RecordMeta:
    tag_info: TagInfo
    vehicle: str
    date: str
    last_update: Dict[str, str] = field(default_factory=dict)
    files: Dict[str, List[str]] = field(default_factory=dict)

    @classmethod
    def from_task_entry(
        cls,
        task_entry: TaskEntry,
        vehicle: str,
        date: str,
        before: int,
        after: int,
    ) -> "RecordMeta":
        return cls(
            tag_info=TagInfo.from_task_entry(task_entry, before, after),
            vehicle=vehicle,
            date=date,
        )

    @classmethod
    def from_dict(cls, raw_meta: RawRecordMeta) -> "RecordMeta":
        raw_tag_info: Dict[str, Union[str, int]] = raw_meta.get("tag_info") or {}
        return cls(
            tag_info=TagInfo(
                name=str(raw_tag_info.get("name", "")),
                time=str(raw_tag_info.get("time", "")),
                offset_bf=int(raw_tag_info.get("offset_bf", 0)),
                offset_af=int(raw_tag_info.get("offset_af", 0)),
                abs_start=str(raw_tag_info.get("abs_start", "")),
                abs_end=str(raw_tag_info.get("abs_end", "")),
            ),
            vehicle=str(raw_meta.get("vehicle", "")),
            date=str(raw_meta.get("date", "")),
            last_update={
                str(soc_name): str(update_time)
                for soc_name, update_time in (raw_meta.get("last_update") or {}).items()
            },
            files={
                str(soc_name): [str(file_name) for file_name in file_names]
                for soc_name, file_names in (raw_meta.get("files") or {}).items()
            },
        )

    def merge_existing(self, existing_meta: "RecordMeta") -> None:
        """合并已有 metadata 的更新时间和文件映射。"""
        self.last_update = dict(existing_meta.last_update)
        self.files = {
            soc_name: list(file_names)
            for soc_name, file_names in existing_meta.files.items()
        }

    def update_soc_files(
        self,
        soc_name: str,
        file_names: Sequence[str],
        updated_at: Optional[str] = None,
    ) -> None:
        self.files[soc_name] = list(file_names)
        self.last_update[soc_name] = updated_at or datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    @property
    def replay_duration(self) -> int:
        """返回当前 tag 窗口对应的回放总时长。"""
        return self.tag_info.offset_bf + self.tag_info.offset_af

    def build_replay_record(self, file_path: Path) -> ReplayRecord:
        """基于当前元数据窗口为单个文件构造回放记录。"""
        return ReplayRecord(
            path=str(file_path.absolute()),
            begin=self.tag_info.abs_start,
            duration=self.replay_duration,
        )

    def build_soc_replay_records(
        self,
        tag_dir: Path,
        soc_name: str,
    ) -> List[ReplayRecord]:
        """根据当前 meta 和 tag 目录恢复某个 SOC 的回放文件列表。"""
        soc_path = tag_dir / soc_name
        if not soc_path.exists():
            return []
        replay_records = []
        for file_name in self.files.get(soc_name, []):
            file_path = soc_path / file_name
            if file_path.exists():
                replay_records.append(self.build_replay_record(file_path))
        return sorted(replay_records, key=lambda replay_record: replay_record.begin)

    def to_dict(self) -> RawRecordMeta:
        return {
            "tag_info": {
                "name": self.tag_info.name,
                "time": self.tag_info.time,
                "offset_bf": self.tag_info.offset_bf,
                "offset_af": self.tag_info.offset_af,
                "abs_start": self.tag_info.abs_start,
                "abs_end": self.tag_info.abs_end,
            },
            "vehicle": self.vehicle,
            "date": self.date,
            "last_update": self.last_update,
            "files": self.files,
        }


@dataclass
class RecordInfo:
    begin: datetime
    end: datetime
    duration: int
    channels: List[ChannelInfo] = field(default_factory=list)

    @classmethod
    def from_components(
        cls,
        begin: datetime,
        end: datetime,
        duration: Union[int, float],
        channels: Iterable[ChannelInfo],
    ) -> "RecordInfo":
        return cls(
            begin=begin,
            end=end,
            duration=int(duration),
            channels=sorted(list(channels), key=lambda channel: channel.name),
        )
