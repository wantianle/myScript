from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Union


@dataclass
class TaskEntry:
    time: str
    name: str
    soc_paths: Dict[str, List[str]]
    paths: List[str]
    id: str = field(default="")


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
    def from_dict(cls, raw_logic: Dict[str, Any]) -> "LogicConfig":
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
    def from_dict(cls, raw_host: Dict[str, Any]) -> "HostConfig":
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
    def from_dict(cls, raw_remote: Dict[str, Any]) -> "RemoteConfig":
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
    def from_dict(cls, raw_docker: Dict[str, Any]) -> "DockerConfig":
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
    def from_dict(cls, raw_paths: Dict[str, Any]) -> "PathsConfig":
        return cls(
            scripts_dir=str(raw_paths.get("scripts_dir", "")),
        )


@dataclass
class ReplayRecord:
    path: str
    begin: Union[str, datetime]
    duration: int


@dataclass
class LibraryEntry:
    tag: str
    time: str
    vehicle: str
    date: str
    socs: Dict[str, List[ReplayRecord]] = field(default_factory=dict)
    last_update: Dict[str, str] = field(default_factory=dict)


@dataclass
class ChannelInfo:
    name: str
    count: int


@dataclass
class RecordInfo:
    begin: datetime
    end: datetime
    duration: int
    channels: List[ChannelInfo] = field(default_factory=list)
