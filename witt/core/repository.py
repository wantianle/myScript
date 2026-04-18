import json
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

from core.models import LibraryEntry, RecordMeta, ReplayHistoryEntry


class LibraryCacheRepository:
    """负责本地回放库缓存文件的读写。"""

    def __init__(self, cache_path: Path) -> None:
        self.cache_path = cache_path

    def load(self, fingerprint: str) -> Optional[List[LibraryEntry]]:
        """按指纹读取缓存命中的回放库。"""
        if not self.cache_path.exists():
            return None
        raw_cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
        if raw_cache.get("fingerprint") != fingerprint or not raw_cache.get("library"):
            return None
        return [
            LibraryEntry.from_cache_dict(raw_entry)
            for raw_entry in raw_cache.get("library", [])
        ]

    def save(self, fingerprint: str, library_entries: List[LibraryEntry]) -> None:
        """写入当前回放库缓存。"""
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(
                {
                    "fingerprint": fingerprint,
                    "library": [
                        library_entry.to_cache_dict()
                        for library_entry in library_entries
                    ],
                },
                indent=4,
                ensure_ascii=False,
            )
        )


class MetadataRepository:
    """负责 meta.json 的读写与扫描。"""

    def iter_record_meta(self, root_dir: Path) -> Iterator[Tuple[Path, RecordMeta]]:
        """扫描目录下所有 meta.json 并返回目录与解析结果。"""
        for meta_path in root_dir.rglob("meta.json"):
            yield meta_path.parent, self.load(meta_path)

    def load(self, meta_path: Path) -> RecordMeta:
        """读取单个 meta.json 并转换成 RecordMeta。"""
        raw_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return RecordMeta.from_dict(raw_meta)

    def save(self, meta_path: Path, record_meta: RecordMeta) -> None:
        """将 RecordMeta 写回 meta.json。"""
        meta_path.write_text(
            json.dumps(record_meta.to_dict(), indent=4, ensure_ascii=False)
        )


class ReplayHistoryRepository:
    """负责回播历史记录的读写。"""

    def __init__(self, history_path: Path, limit: int = 50) -> None:
        self.history_path = history_path
        self.limit = limit

    def load(self) -> List[ReplayHistoryEntry]:
        """读取全部回播历史。"""
        if not self.history_path.exists():
            return []
        raw_history = json.loads(self.history_path.read_text(encoding="utf-8"))
        raw_entries = raw_history.get("entries", [])
        return [
            ReplayHistoryEntry.from_dict(raw_entry)
            for raw_entry in raw_entries
        ]

    def load_last(self) -> Optional[ReplayHistoryEntry]:
        """读取最近一次回播历史。"""
        history_entries = self.load()
        return history_entries[-1] if history_entries else None

    def save(self, history_entries: List[ReplayHistoryEntry]) -> None:
        """保存回播历史列表。"""
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        trimmed_entries = history_entries[-self.limit :] if self.limit > 0 else history_entries
        self.history_path.write_text(
            json.dumps(
                {
                    "entries": [
                        history_entry.to_dict()
                        for history_entry in trimmed_entries
                    ]
                },
                indent=4,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def append(self, history_entry: ReplayHistoryEntry) -> None:
        """追加一条回播历史。"""
        history_entries = self.load()
        history_entries.append(history_entry)
        self.save(history_entries)

    def clear(self) -> None:
        """清空全部回播历史。"""
        self.save([])
