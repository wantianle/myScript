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
    cache_path: Path


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

    @property
    def executor(self):
        """返回当前会话对应的执行适配器。"""
        return self.session.executor

    @property
    def library_file(self):
        """返回本地回放库缓存文件路径。"""
        return self.library_cache.cache_path

    def load_library(self) -> LibraryLoadResult:
        """加载本地回放库，必要时重扫目录并刷新缓存。"""
        fp = self.ctx.get_library_fingerprint()
        cached_library = self.library_cache.load(fp)
        if cached_library is not None:
            return LibraryLoadResult(
                library=cached_library,
                cache_hit=True,
                cache_path=self.library_file,
            )
        library_list = self.scan_local_library()
        self.library_cache.save(fp, library_list)
        return LibraryLoadResult(
            library=library_list,
            cache_hit=False,
            cache_path=self.library_file,
        )

    def scan_local_library(self) -> List[LibraryEntry]:
        """扫描工作目录中的 metadata，构建回放库对象。"""
        library_map = {}
        for tag_dir, record_meta in self.metadata_repository.iter_record_meta(self.ctx.work_dir):
            try:
                tag_entry = LibraryEntry.from_record_meta(record_meta, tag_dir)
                library_map[str(tag_dir)] = tag_entry
            except Exception as e:
                raise RuntimeError(f"[{tag_dir / 'meta.json'}] 元数据解析失败") from e
        return sorted(list(library_map.values()), key=lambda library_entry: library_entry.time)

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

        def ensure_dt(val):
            return datetime.fromisoformat(val) if isinstance(val, str) else val

        global_start = ensure_dt(records[0].begin)
        total_duration = max(replay_record.duration for replay_record in records)
        if total_duration <= 0:
            raise ValueError("数据总时长无效，无法播放")
        if playback_rate < 0.1 or playback_rate > 10:
            raise ValueError("播放倍速需在 0.1 到 10 之间")
        # 构造指令
        docker_paths = [self.executor.map_path(replay_record.path) for replay_record in records]
        cmd_parts = ["cyber_recorder play", "-l", "-f", " ".join(docker_paths)]
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
            f'-b "{(global_start + timedelta(seconds=final_start)).strftime(fmt)}"'
        )
        cmd_parts.append(
            f'-e "{(global_start + timedelta(seconds=final_end)).strftime(fmt)}"'
        )
        return PlaybackPlan(
            command=" ".join(cmd_parts),
            duration=total_duration,
            display_tag=Path(records[0].path).name[:20] + "...",
            rate=playback_rate,
        )
