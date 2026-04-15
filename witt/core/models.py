from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class TaskEntry:
    time: str
    name: str
    soc_paths: Dict[str, List[str]]
    paths: List[str]
    id: str = field(default="")
