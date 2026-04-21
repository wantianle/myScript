from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, TYPE_CHECKING

from core.models import LibraryEntry, ReplayRecord
from core.repository import LibraryCacheRepository, MetadataRepository

if TYPE_CHECKING:
    from core.session import AppSession


@dataclass
class LibraryLoadResult:
    library: List[LibraryEntry]
    cache_hit: bool


@dataclass
class PlaybackPlan:
    command: str
    duration: int
    display_tag: str
    rate: float


class RecordPlayer:
    def __init__(
        self,
        session: "AppSession",
        library_cache: LibraryCacheRepository,
        metadata_repository: MetadataRepository,
    ) -> None:
        self.session = session
        self.ctx = session.ctx
        self.library_cache = library_cache
        self.metadata_repository = metadata_repository

    def load_library(self) -> LibraryLoadResult:
        """加载本地回放库，必要时重扫目录并刷新缓存。"""
        fingerprint = self.ctx.get_library_fingerprint()
        cached_library = self.library_cache.load(fingerprint)
        if cached_library is not None:
            return LibraryLoadResult(
                library=cached_library,
                cache_hit=True,
            )
        library_entries = []
        for tag_dir, record_meta in self.metadata_repository.iter_record_meta(self.ctx.work_dir):
            try:
                library_entries.append(
                    LibraryEntry.from_record_meta(record_meta, tag_dir)
                )
            except Exception as e:
                raise RuntimeError(f"[{tag_dir / 'meta.json'}] 元数据解析失败") from e
        library_entries.sort(key=lambda library_entry: library_entry.time)
        self.library_cache.save(fingerprint, library_entries)
        return LibraryLoadResult(
            library=library_entries,
            cache_hit=False,
        )

    def build_playback_plan(
        self,
        records: List[ReplayRecord],
        start_sec: int = 0,
        end_sec: int = 0,
        playback_rate: float = 1.0,
    ) -> PlaybackPlan:
        """根据回放记录和时间窗构建最终执行计划。"""
        if not records:
            raise ValueError("播放列表为空")
        playback_start_time = records[0].begin
        if isinstance(playback_start_time, str):
            playback_start_time = datetime.fromisoformat(playback_start_time)
        total_duration = max(replay_record.duration for replay_record in records)
        if total_duration <= 0:
            raise ValueError("数据总时长无效，无法播放")
        if not 0.1 <= playback_rate <= 10:
            raise ValueError("播放倍速需在 0.1 到 10 之间")
        mapped_paths = [
            self.session.executor.map_path(replay_record.path)
            for replay_record in records
        ]
        cmd_parts = ["cyber_recorder play", "-l", "-f", " ".join(mapped_paths)]
        cmd_parts.append("-r {0:g}".format(playback_rate))
        blacklist = getattr(self.ctx, "playback_blacklist", [])
        if blacklist:
            for channel_name in blacklist:
                cmd_parts.append(f"-k {channel_name}")
        # 时间窗
        fmt = "%Y-%m-%d %H:%M:%S"
        final_start = max(0, start_sec)
        if final_start >= total_duration:
            raise ValueError("播放起点超出数据总时长")
        if end_sec > 0 and end_sec <= final_start:
            raise ValueError("播放时间范围无效，结束时间必须大于开始时间")
        final_end = total_duration if end_sec <= 0 else min(end_sec, total_duration)
        cmd_parts.append(
            f'-b "{(playback_start_time + timedelta(seconds=final_start)).strftime(fmt)}"'
        )
        cmd_parts.append(
            f'-e "{(playback_start_time + timedelta(seconds=final_end)).strftime(fmt)}"'
        )
        record_name = Path(records[0].path).name
        return PlaybackPlan(
            command=" ".join(cmd_parts),
            duration=total_duration,
            display_tag=record_name[:20] + "...",
            rate=playback_rate,
        )
