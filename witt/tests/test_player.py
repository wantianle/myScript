import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock, patch

from core.engine.player import RecordPlayer
from core.models import LibraryEntry
from core.models import ReplayRecord


class _FakeExecutor:
    def map_path(self, path_text: str) -> str:
        return "/docker{0}".format(path_text)


class RecordPlayerTests(unittest.TestCase):
    def test_load_library_returns_cached_entries_when_fingerprint_hits(self) -> None:
        cached_library = [cast(Any, object())]
        raw_session = SimpleNamespace(
            ctx=SimpleNamespace(
                get_library_fingerprint=Mock(return_value="fp-1"),
                work_dir=Path("/tmp/work"),
            ),
            playback_executor=_FakeExecutor(),
        )
        library_cache = SimpleNamespace(
            load=Mock(return_value=cached_library),
            save=Mock(),
        )
        player = RecordPlayer(
            cast(Any, raw_session),
            cast(Any, library_cache),
            cast(Any, SimpleNamespace()),
        )

        library_result = player.load_library()

        self.assertTrue(library_result.cache_hit)
        self.assertIs(library_result.library, cached_library)
        library_cache.load.assert_called_once_with("fp-1")
        library_cache.save.assert_not_called()

    def test_load_library_scans_and_saves_when_cache_misses(self) -> None:
        raw_session = SimpleNamespace(
            ctx=SimpleNamespace(
                get_library_fingerprint=Mock(return_value="fp-1"),
                work_dir=Path("/tmp/work"),
            ),
            playback_executor=_FakeExecutor(),
        )
        library_cache = SimpleNamespace(
            load=Mock(return_value=None),
            save=Mock(),
        )
        metadata_repository = SimpleNamespace(
            iter_record_meta=Mock(
                return_value=[
                    (Path("/tmp/work/tag_b"), cast(Any, object())),
                    (Path("/tmp/work/tag_a"), cast(Any, object())),
                ]
            )
        )
        player = RecordPlayer(
            cast(Any, raw_session),
            cast(Any, library_cache),
            cast(Any, metadata_repository),
        )
        tag_b = LibraryEntry(tag="tag_b", time="2026-04-15 12:00:01")
        tag_a = LibraryEntry(tag="tag_a", time="2026-04-15 12:00:00")

        with patch(
            "core.engine.player.LibraryEntry.from_record_meta",
            side_effect=[tag_b, tag_a],
        ) as from_record_meta:
            library_result = player.load_library()

        self.assertFalse(library_result.cache_hit)
        self.assertEqual(library_result.library, [tag_a, tag_b])
        metadata_repository.iter_record_meta.assert_called_once_with(Path("/tmp/work"))
        self.assertEqual(from_record_meta.call_count, 2)
        library_cache.save.assert_called_once_with("fp-1", [tag_a, tag_b])

    def test_build_playback_plan_appends_blacklist_args(self) -> None:
        raw_session = SimpleNamespace(
            ctx=SimpleNamespace(
                playback_blacklist=["/apollo/foo", "/apollo/bar"],
            ),
            playback_executor=_FakeExecutor(),
        )
        player = RecordPlayer(
            cast(Any, raw_session),
            cast(Any, SimpleNamespace(cache_path=Path("/tmp/library.json"))),
            cast(Any, SimpleNamespace()),
        )
        records = [
            ReplayRecord(
                path="/data/demo.record",
                begin="2026-04-15T12:00:00",
                duration=20,
            )
        ]

        playback_plan = player.build_playback_plan(records, 1, 3, 2.5)

        self.assertIn("cyber_recorder play -l -f /docker/data/demo.record", playback_plan.command)
        self.assertIn("-r 2.5", playback_plan.command)
        self.assertIn("-k /apollo/foo", playback_plan.command)
        self.assertIn("-k /apollo/bar", playback_plan.command)
        self.assertIn('-b "2026-04-15 12:00:01"', playback_plan.command)
        self.assertIn('-e "2026-04-15 12:00:03"', playback_plan.command)
        self.assertEqual(playback_plan.rate, 2.5)

    def test_build_playback_plan_rejects_out_of_range_speed(self) -> None:
        raw_session = SimpleNamespace(
            ctx=SimpleNamespace(playback_blacklist=[]),
            playback_executor=_FakeExecutor(),
        )
        player = RecordPlayer(
            cast(Any, raw_session),
            cast(Any, SimpleNamespace(cache_path=Path("/tmp/library.json"))),
            cast(Any, SimpleNamespace()),
        )
        records = [
            ReplayRecord(
                path="/data/demo.record",
                begin="2026-04-15T12:00:00",
                duration=20,
            )
        ]

        with self.assertRaises(ValueError):
            player.build_playback_plan(records, 0, 0, 10.1)


if __name__ == "__main__":
    unittest.main()
