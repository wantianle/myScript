from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Union


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
    def from_dict(cls, raw_logic: Dict[str, object]) -> "LogicConfig":
        raw_blacklist = raw_logic.get("blacklist")
        if isinstance(raw_blacklist, list):
            blacklist = [str(item) for item in raw_blacklist]
        elif raw_blacklist:
            blacklist = [str(raw_blacklist)]
        else:
            blacklist = []
        return cls(
            vehicle=str(raw_logic.get("vehicle", "")),
            target_date=str(raw_logic.get("target_date", "")),
            mode=int(raw_logic.get("mode", 0)),
            version=raw_logic.get("version", "") or "",
            soc=str(raw_logic.get("soc", "")),
            before=int(raw_logic.get("before", 0)),
            after=int(raw_logic.get("after", 0)),
            blacklist=blacklist,
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
