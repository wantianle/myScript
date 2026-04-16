import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from core.engine.player import RecordPlayer
from core.models import ReplayRecord


class _FakeExecutor:
    def map_path(self, path_text: str) -> str:
        return "/docker{0}".format(path_text)


class RecordPlayerTests(unittest.TestCase):
    def test_build_playback_plan_appends_blacklist_args(self) -> None:
        raw_session = SimpleNamespace(
            ctx=SimpleNamespace(
                playback_blacklist=["/apollo/foo", "/apollo/bar"],
            ),
            executor=_FakeExecutor(),
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
            executor=_FakeExecutor(),
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
