import sys
import unittest
from types import ModuleType, SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from core.models import LibraryEntry, ReplayRecord, TaskEntry

fake_questionary = ModuleType("questionary")


class _FakeChoice:
    def __init__(self, title=None, value=None):
        self.title = title
        self.value = value


def _fake_style(value):
    return value


def _fake_select(*args, **kwargs):
    class _Prompt:
        def ask(self):
            return None

    return _Prompt()


def _fake_checkbox(*args, **kwargs):
    class _Prompt:
        def ask(self):
            return []

    return _Prompt()


setattr(fake_questionary, "Choice", _FakeChoice)
setattr(fake_questionary, "Style", _fake_style)
setattr(fake_questionary, "select", _fake_select)
setattr(fake_questionary, "checkbox", _fake_checkbox)
sys.modules.setdefault("questionary", fake_questionary)

fake_alive_progress = ModuleType("alive_progress")


def _fake_alive_bar(*args, **kwargs):
    class _Bar:
        def __enter__(self):
            return lambda *bar_args, **bar_kwargs: None

        def __exit__(self, exc_type, exc, tb):
            return False

    return _Bar()


setattr(fake_alive_progress, "alive_bar", _fake_alive_bar)
sys.modules.setdefault("alive_progress", fake_alive_progress)

from interface import cli
from interface import replay_workflow
from interface import workflow


class CliMenuTests(unittest.TestCase):
    def test_menu_routes_choice_1_to_slice_progress(self) -> None:
        session = object()

        with patch.object(cli, "AppSession", return_value=session), patch.object(
            cli.ui,
            "print_banner",
        ), patch.object(
            cli.prompter,
            "select_main_menu_action",
            side_effect=["1", "q"],
        ), patch.object(
            cli.prompter,
            "wait_for_continue",
        ), patch.object(
            cli.workflow,
            "slice_progress",
        ) as slice_progress, patch.object(
            cli.workflow,
            "full_source_progress",
        ) as full_source_progress:
            with self.assertRaises(SystemExit):
                cli.menu()

        slice_progress.assert_called_once_with(session)
        full_source_progress.assert_not_called()

    def test_menu_routes_choice_2_to_full_source_progress(self) -> None:
        session = object()

        with patch.object(cli, "AppSession", return_value=session), patch.object(
            cli.ui,
            "print_banner",
        ), patch.object(
            cli.prompter,
            "select_main_menu_action",
            side_effect=["2", "q"],
        ), patch.object(
            cli.prompter,
            "wait_for_continue",
        ), patch.object(
            cli.workflow,
            "slice_progress",
        ) as slice_progress, patch.object(
            cli.workflow,
            "full_source_progress",
        ) as full_source_progress:
            with self.assertRaises(SystemExit):
                cli.menu()

        full_source_progress.assert_called_once_with(session)
        slice_progress.assert_not_called()


class WorkflowTests(unittest.TestCase):
    def test_full_source_progress_filters_invalid_tasks(self) -> None:
        raw_session = SimpleNamespace(
            ctx=SimpleNamespace(manifest_path="/tmp/tasks.list")
        )
        session = cast(Any, raw_session)
        empty_task = TaskEntry.from_manifest_parts(
            time="2026-04-15 12:00:00",
            name="empty_tag",
            paths=[],
        )
        valid_task = TaskEntry.from_manifest_parts(
            time="2026-04-15 12:00:01",
            name="demo_tag",
            paths=["/data/soc1/a.record"],
        )

        with patch.object(workflow, "search_flow") as search_flow, patch.object(
            workflow.parser,
            "parse_manifest",
            return_value=[empty_task, valid_task],
        ), patch.object(
            workflow.replay_workflow,
            "full_source_replay_flow",
        ) as full_source_replay_flow:
            workflow.full_source_progress(session)

        search_flow.assert_called_once_with(raw_session, need_export_path=False)
        full_source_replay_flow.assert_called_once_with(raw_session, [valid_task])


class ReplayWorkflowTests(unittest.TestCase):
    def test_auto_replay_flow_replays_selected_library_records(self) -> None:
        target_record = ReplayRecord(
            path="/data/soc1/20260414103914.record.00000.103914",
            begin="2026-04-15T11:59:45",
            duration=15,
        )
        library_entry = LibraryEntry(
            tag="demo_tag",
            time="2026-04-15 12:00:00",
            vehicle="XZB600013",
            date="20260415",
            socs={"soc1": [target_record]},
        )
        raw_session = SimpleNamespace(
            ctx=SimpleNamespace(
                work_dir="/tmp/work",
                vehicle="XZB600013",
                target_date="20260415",
            ),
            player=SimpleNamespace(load_library=lambda: None),
        )
        session = cast(Any, raw_session)
        library_result = SimpleNamespace(
            cache_hit=True,
            cache_path="/tmp/cache.json",
            library=[library_entry],
        )

        with patch.object(
            raw_session.player,
            "load_library",
            return_value=library_result,
        ), patch.object(
            replay_workflow.replay_prompter,
            "select_playback_entry",
            side_effect=[library_entry, None],
        ), patch.object(
            replay_workflow.replay_prompter,
            "select_replay_records",
            return_value=[target_record],
        ), patch.object(
            replay_workflow,
            "_update_playback_blacklist",
        ), patch.object(
            replay_workflow,
            "_replay_records",
        ) as replay_records:
            replay_workflow.auto_replay_flow(
                session,
                replay_workflow.REPLAY_MODE_STANDARD,
            )

        replay_records.assert_called_once()
        args, _ = replay_records.call_args
        self.assertEqual(args[0], raw_session)
        self.assertEqual(args[1], [target_record])
        self.assertEqual(args[2], replay_workflow.REPLAY_MODE_STANDARD)

    def test_full_source_replay_flow_replays_selected_task(self) -> None:
        raw_session = SimpleNamespace(
            ctx=SimpleNamespace(find_record_output=""),
        )
        session = cast(Any, raw_session)
        task_entry = TaskEntry.from_manifest_parts(
            time="2026-04-15 12:00:00",
            name="demo_tag",
            paths=["/data/soc1/a.record"],
        )
        source_records = [
            ReplayRecord(
                path="/data/soc1/a.record",
                begin="2026-04-15T11:59:45",
                duration=20,
            )
        ]

        with patch.object(
            replay_workflow.replay_prompter,
            "select_source_task_entry",
            side_effect=[task_entry, None],
        ), patch.object(
            replay_workflow,
            "_build_source_replay_records",
            return_value=source_records,
        ), patch.object(
            replay_workflow,
            "_update_playback_blacklist",
        ), patch.object(
            replay_workflow,
            "_replay_records",
        ) as replay_records:
            replay_workflow.full_source_replay_flow(session, [task_entry])

        replay_records.assert_called_once()
        args, _ = replay_records.call_args
        self.assertEqual(args[0], raw_session)
        self.assertEqual(args[1], source_records)
        self.assertEqual(args[2], replay_workflow.REPLAY_MODE_STANDARD)


if __name__ == "__main__":
    unittest.main()
