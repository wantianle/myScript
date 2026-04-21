import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from core.engine.record_query import RecordQueryService
from core.models import TaskEntry

class RecordQueryServiceTests(unittest.TestCase):
    def test_run_query_uses_local_root_for_mode_1(self) -> None:
        task_entries = [
            TaskEntry.from_record_paths(
                time="2026-04-19 12:00:00",
                name="demo_tag",
                paths=["/tmp/local_root/soc1/a.record"],
            )
        ]
        ctx = cast(
            Any,
            SimpleNamespace(
                host=SimpleNamespace(
                    data_root="/tmp/local_root",
                    nas_root="/tmp/nas_root",
                ),
                logic=SimpleNamespace(
                    mode=1,
                    before=15,
                    after=5,
                    soc="soc1",
                    target_date="20260419",
                    vehicle="XZB600001",
                ),
            ),
        )
        record_query_service = RecordQueryService(ctx)

        with patch(
            "core.engine.record_query.record_finder.find_local_tasks",
            return_value=task_entries,
        ) as find_local_tasks:
            returned_tasks = record_query_service.run_query()

        find_local_tasks.assert_called_once_with(
            Path("/tmp/local_root"),
            target_date="20260419",
            before=15,
            after=5,
            soc_filter="soc1",
        )
        self.assertEqual(returned_tasks, task_entries)

    def test_run_query_uses_nas_root_for_mode_2(self) -> None:
        ctx = cast(
            Any,
            SimpleNamespace(
                host=SimpleNamespace(
                    data_root="/tmp/local_root",
                    nas_root="/tmp/nas_root",
                ),
                logic=SimpleNamespace(
                    mode=2,
                    before=15,
                    after=5,
                    soc="",
                    target_date="20260419",
                    vehicle="XZB600001",
                ),
            ),
        )
        record_query_service = RecordQueryService(ctx)

        with patch(
            "core.engine.record_query.record_finder.find_local_tasks",
            return_value=[],
        ) as find_local_tasks:
            returned_tasks = record_query_service.run_query()

        find_local_tasks.assert_called_once_with(
            Path("/tmp/nas_root/20260419/XZB600001"),
            target_date="20260419",
            before=15,
            after=5,
            soc_filter="",
        )
        self.assertEqual(returned_tasks, [])

    def test_run_query_uses_remote_paths_for_mode_3(self) -> None:
        task_entries = [
            TaskEntry.from_record_paths(
                time="2026-04-19 12:00:00",
                name="demo_tag",
                paths=["/remote/root/soc1/a.record"],
            )
        ]
        ctx = cast(
            Any,
            SimpleNamespace(
                remote=SimpleNamespace(
                    user="mini",
                    ip="10.0.0.1",
                    data_root="/remote/root",
                ),
                host=SimpleNamespace(
                    data_root="/tmp/local_root",
                    nas_root="/tmp/nas_root",
                ),
                logic=SimpleNamespace(
                    mode=3,
                    before=15,
                    after=5,
                    soc="",
                    target_date="20260419",
                    vehicle="XZB600001",
                ),
            ),
        )
        record_query_service = RecordQueryService(ctx)

        with patch.object(
            record_query_service,
            "_run_remote_find_paths",
            return_value=["/remote/root/demo_tag_20260419.pb.txt"],
        ) as run_remote_find_paths, patch(
            "core.engine.record_query.record_finder.find_tasks_from_path_texts",
            return_value=task_entries,
        ) as find_tasks_from_path_texts:
            returned_tasks = record_query_service.run_query()

        run_remote_find_paths.assert_called_once_with()
        find_tasks_from_path_texts.assert_called_once()
        self.assertEqual(returned_tasks, task_entries)


if __name__ == "__main__":
    unittest.main()
