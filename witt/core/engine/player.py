import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

from core.models import LibraryEntry, ReplayRecord


@dataclass
class LibraryLoadResult:
    library: List[LibraryEntry]
    cache_hit: bool
    cache_path: Path


@dataclass
class PlaybackPlan:
    command: str
    duration: int
    display_tag: str


class RecordPlayer:
    def __init__(self, session):
        self.session = session
        self.ctx = session.ctx

    @property
    def executor(self):
        return self.session.executor

    @property
    def library_file(self):
        return self.ctx.work_dir / ".witt" / "local_library.json"

    def load_library(self) -> LibraryLoadResult:
        fp = self.ctx.get_library_fingerprint()
        if self.library_file.exists():
            data = json.loads(self.library_file.read_text(encoding="utf-8"))
            if data.get("fingerprint") == fp and data.get("library"):
                return LibraryLoadResult(
                    library=self._deserialize_library(data.get("library", [])),
                    cache_hit=True,
                    cache_path=self.library_file,
                )
        library_list = self.scan_local_library()
        save_obj = {"fingerprint": fp, "library": library_list}
        self.library_file.parent.mkdir(parents=True, exist_ok=True)
        self.library_file.write_text(
            json.dumps(
                {
                    "fingerprint": save_obj["fingerprint"],
                    "library": self._serialize_library(library_list),
                },
                indent=4,
                ensure_ascii=False,
            )
        )
        return LibraryLoadResult(
            library=library_list,
            cache_hit=False,
            cache_path=self.library_file,
        )

    def _serialize_library(self, library_entries: List[LibraryEntry]):
        serialized_entries = []
        for library_entry in library_entries:
            serialized_entries.append(
                {
                    "tag": library_entry.tag,
                    "time": library_entry.time,
                    "vehicle": library_entry.vehicle,
                    "date": library_entry.date,
                    "last_update": library_entry.last_update,
                    "socs": {
                        soc_name: [
                            {
                                "path": replay_record.path,
                                "begin": replay_record.begin,
                                "duration": replay_record.duration,
                            }
                            for replay_record in replay_records
                        ]
                        for soc_name, replay_records in library_entry.socs.items()
                    },
                }
            )
        return serialized_entries

    def _deserialize_library(self, raw_library) -> List[LibraryEntry]:
        deserialized_entries = []
        for raw_entry in raw_library:
            deserialized_entries.append(
                LibraryEntry(
                    tag=raw_entry["tag"],
                    time=raw_entry["time"],
                    vehicle=raw_entry["vehicle"],
                    date=raw_entry["date"],
                    last_update=raw_entry.get("last_update") or {},
                    socs={
                        soc_name: [
                            ReplayRecord(
                                path=raw_record["path"],
                                begin=raw_record["begin"],
                                duration=raw_record["duration"],
                            )
                            for raw_record in raw_records
                        ]
                        for soc_name, raw_records in raw_entry.get("socs", {}).items()
                    },
                )
            )
        return deserialized_entries

    def scan_local_library(self) -> List[LibraryEntry]:
        library_map = {}
        for meta_file in self.ctx.work_dir.rglob("meta.json"):
            tag_dir = meta_file.parent
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                tag_name = meta["tag_info"]["name"]
                tag_entry = LibraryEntry(
                    tag=tag_name,
                    time=meta["tag_info"]["time"],
                    vehicle=meta.get("vehicle", tag_dir.parent.name),
                    date=meta.get("date", tag_dir.parents[1].name),
                    last_update=meta.get("last_update") or {},
                )
                for soc_name, file_names in meta.get("files", {}).items():
                    soc_path = tag_dir / soc_name
                    if not soc_path.exists():
                        continue
                    record_details = []
                    for fname in file_names:
                        f_abs_path = soc_path / fname
                        if f_abs_path.exists():
                            record_details.append(
                                ReplayRecord(
                                    path=str(f_abs_path.absolute()),
                                    begin=meta["tag_info"]["abs_start"],
                                    duration=meta["tag_info"]["offset_bf"]
                                    + meta["tag_info"]["offset_af"],
                                )
                            )
                    if record_details:
                        record_details.sort(key=lambda replay_record: replay_record.begin)
                        tag_entry.socs[soc_name] = record_details
                library_map[str(tag_dir)] = tag_entry
            except Exception as e:
                raise RuntimeError(f"[{meta_file}] 元数据解析失败") from e
        return sorted(list(library_map.values()), key=lambda library_entry: library_entry.time)

    def build_playback_plan(
        self,
        records: List[ReplayRecord],
        start_sec: int = 0,
        end_sec: int = 0,
    ) -> PlaybackPlan:
        if not records:
            raise ValueError("播放列表为空")

        def ensure_dt(val):
            return datetime.fromisoformat(val) if isinstance(val, str) else val

        global_start = ensure_dt(records[0].begin)
        total_duration = max(replay_record.duration for replay_record in records)
        if total_duration <= 0:
            raise ValueError("数据总时长无效，无法播放")
        # 构造指令
        docker_paths = [self.executor.map_path(replay_record.path) for replay_record in records]
        cmd_parts = ["cyber_recorder play", "-l", "-f", " ".join(docker_paths)]
        # 时间窗
        fmt = "%Y-%m-%d %H:%M:%S"
        final_start = max(0, start_sec)
        if final_start >= total_duration:
            raise ValueError("播放起点超出数据总时长")
        if end_sec > 0 and end_sec <= final_start:
            raise ValueError("播放时间范围无效，结束时间必须大于开始时间")
        final_end = total_duration if end_sec <= 0 else min(end_sec, total_duration)
        cmd_parts.append(
            f'-b "{(global_start + timedelta(seconds=final_start)).strftime(fmt)}"'
        )
        cmd_parts.append(
            f'-e "{(global_start + timedelta(seconds=final_end)).strftime(fmt)}"'
        )
        return PlaybackPlan(
            command=" ".join(cmd_parts),
            duration=total_duration,
            display_tag=Path(records[0].path).name[:20] + "...",
        )
