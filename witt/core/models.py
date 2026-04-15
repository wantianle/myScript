from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Union


@dataclass
class TaskEntry:
    time: str
    name: str
    soc_paths: Dict[str, List[str]]
    paths: List[str]
    id: str = field(default="")


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
