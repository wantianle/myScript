import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

from core.models import LibraryEntry, RecordMeta, ReplayRecord


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
        """返回当前会话对应的执行适配器。"""
        return self.session.executor

    @property
    def library_file(self):
        """返回本地回放库缓存文件路径。"""
        return self.ctx.work_dir / ".witt" / "local_library.json"

    def load_library(self) -> LibraryLoadResult:
        """加载本地回放库，必要时重扫目录并刷新缓存。"""
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

    def _serialize_library(
        self,
        library_entries: List[LibraryEntry],
    ) -> List[Dict[str, Any]]:
        """将回放库对象转换为可写入 JSON 的结构。"""
        return [library_entry.to_cache_dict() for library_entry in library_entries]

    def _deserialize_library(
        self,
        raw_library: List[Dict[str, Any]],
    ) -> List[LibraryEntry]:
        """将缓存文件中的原始结构还原为回放库对象。"""
        return [LibraryEntry.from_cache_dict(raw_entry) for raw_entry in raw_library]

    def scan_local_library(self) -> List[LibraryEntry]:
        """扫描工作目录中的 metadata，构建回放库对象。"""
        library_map = {}
        for meta_file in self.ctx.work_dir.rglob("meta.json"):
            tag_dir = meta_file.parent
            try:
                record_meta = RecordMeta.from_dict(
                    json.loads(meta_file.read_text(encoding="utf-8"))
                )
                tag_entry = LibraryEntry.from_record_meta(record_meta, tag_dir)
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
        """根据回放记录和时间窗构建最终执行计划。"""
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
