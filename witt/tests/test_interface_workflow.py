import sys
import unittest
from io import StringIO
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from core.models import LibraryEntry, ReplayRecord, TaskEntry
from core.runner import ScriptRunner

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


fake_questionary.Choice = _FakeChoice
fake_questionary.Style = _fake_style
fake_questionary.select = _fake_select
fake_questionary.checkbox = _fake_checkbox
sys.modules.setdefault("questionary", fake_questionary)

fake_alive_progress = ModuleType("alive_progress")


def _fake_alive_bar(*args, **kwargs):
    class _Bar:
        def __enter__(self):
            return lambda *bar_args, **bar_kwargs: None

        def __exit__(self, exc_type, exc, tb):
            return False

    return _Bar()


fake_alive_progress.alive_bar = _fake_alive_bar
sys.modules.setdefault("alive_progress", fake_alive_progress)

from interface import cli
from interface import replay_prompter
from interface import replay_workflow
from interface import workflow


class CliMenuTests(unittest.TestCase):
    def test_menu_routes_choice_1_to_slice_progress(self) -> None:
        session = object()

        with patch.object(cli, "AppSession", return_value=session), patch.object(
            cli.ui, "print_banner"
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
            cli.ui, "print_banner"
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


class WorkflowSplitTests(unittest.TestCase):
    def test_search_flow_collects_slice_paths_before_split_window(self) -> None:
        call_order = []
        session = SimpleNamespace(
            ctx=object(),
            runner=SimpleNamespace(
                run_find_record=lambda: call_order.append("run_find_record")
            ),
        )

        with patch.object(
            workflow.config_prompter,
            "get_basic_params",
            side_effect=lambda ctx: call_order.append("basic"),
        ), patch.object(
            workflow.config_prompter,
            "get_source_path_params",
            side_effect=lambda ctx: call_order.append("source"),
        ), patch.object(
            workflow.config_prompter,
            "get_export_path_params",
            side_effect=lambda ctx: call_order.append("export"),
        ), patch.object(
            workflow.config_prompter,
            "get_split_params",
            side_effect=lambda ctx: call_order.append("split"),
        ):
            workflow.search_flow(session, need_export_path=True)

        self.assertEqual(
            call_order,
            ["basic", "source", "export", "split", "run_find_record"],
        )

    def test_full_source_progress_reuses_search_and_filters_invalid_tasks(self) -> None:
        session = SimpleNamespace(
            ctx=SimpleNamespace(manifest_path="/tmp/tasks.list")
        )
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

        search_flow.assert_called_once_with(session, need_export_path=False)
        full_source_replay_flow.assert_called_once_with(session, [valid_task])


class ReplayWorkflowDisplayTests(unittest.TestCase):
    def test_auto_replay_flow_uses_library_tag_as_display_tag(self) -> None:
        target_record = ReplayRecord(
            path="/data/soc1/20260414103914.record.00000.103914",
            begin="2026-04-15T11:59:45",
            duration=15,
        )
        library_entry = LibraryEntry(
            tag="中文Tag记录",
            time="2026-04-15 12:00:00",
            vehicle="XZB600013",
            date="20260415",
            socs={"soc1": [target_record]},
        )
        session = SimpleNamespace(
            ctx=SimpleNamespace(
                work_dir="/tmp/work",
                vehicle="XZB600013",
                target_date="20260415",
            ),
            player=SimpleNamespace(
                load_library=lambda: None,
            ),
        )
        library_result = SimpleNamespace(
            cache_hit=True,
            cache_path="/tmp/cache.json",
            library=[library_entry],
        )

        with patch.object(
            session.player,
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
            "_replay_records",
        ) as replay_records:
            replay_workflow.auto_replay_flow(
                session,
                replay_workflow.REPLAY_MODE_STANDARD,
            )

        self.assertEqual(replay_records.call_count, 1)
        args, kwargs = replay_records.call_args
        self.assertEqual(args[0], session)
        self.assertEqual(args[1], [target_record])
        self.assertEqual(args[2], replay_workflow.REPLAY_MODE_STANDARD)
        self.assertEqual(kwargs["display_tag"], "中文Tag记录")

    def test_prepare_replay_uses_standard_only_prompt_for_standard_replay(self) -> None:
        session = SimpleNamespace(
            ctx=SimpleNamespace(logic=SimpleNamespace(version="")),
        )
        records = [
            ReplayRecord(
                path="/data/soc1/a.record",
                begin="2026-04-15T11:59:45",
                duration=20,
            )
        ]

        with patch.object(
            replay_workflow,
            "_resolve_version_from_records",
            return_value=True,
        ), patch.object(
            replay_workflow,
            "restore_environment_flow",
            return_value=True,
        ) as restore_environment_flow:
            replay_workflow._prepare_replay(
                session,
                records,
                replay_workflow.REPLAY_MODE_STANDARD,
            )

        restore_environment_flow.assert_called_once_with(
            session,
            auto=True,
            launch_mode=replay_workflow.LAUNCH_MODE_STANDARD_PROMPT,
        )

    def test_restore_environment_flow_standard_prompt_does_not_ask_traffic_light(self) -> None:
        session = SimpleNamespace(
            ctx=SimpleNamespace(
                logic=SimpleNamespace(version="demo.json"),
            ),
            runner=SimpleNamespace(
                restore_runtime_environment=lambda: None,
                start_standard_replay_stack=lambda: None,
                start_traffic_light_stack=lambda: None,
            ),
        )

        with patch.object(
            replay_workflow.prompter,
            "get_confirm_input",
            return_value=False,
        ) as get_confirm_input, patch.object(
            session.runner,
            "restore_runtime_environment",
        ) as restore_runtime_environment, patch.object(
            session.runner,
            "start_standard_replay_stack",
        ) as start_standard_replay_stack, patch.object(
            session.runner,
            "start_traffic_light_stack",
        ) as start_traffic_light_stack:
            replay_workflow.restore_environment_flow(
                session,
                auto=True,
                launch_mode=replay_workflow.LAUNCH_MODE_STANDARD_PROMPT,
            )

        restore_runtime_environment.assert_called_once_with()
        self.assertEqual(get_confirm_input.call_count, 1)
        self.assertIn(
            "Dreamview & Multiviz",
            get_confirm_input.call_args[0][0],
        )
        start_standard_replay_stack.assert_not_called()
        start_traffic_light_stack.assert_not_called()

    def test_full_source_replay_flow_reuses_saved_find_record_output(self) -> None:
        session = SimpleNamespace(
            ctx=SimpleNamespace(find_record_output="[1] demo_tag : 2026-04-15 12:00:00 [soc1]\n")
        )
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
        ) as select_source_task_entry, patch.object(
            replay_workflow,
            "_build_source_replay_records",
            return_value=source_records,
        ), patch.object(
            replay_workflow,
            "_replay_records",
        ) as replay_records:
            replay_workflow.full_source_replay_flow(session, [task_entry])

        self.assertEqual(select_source_task_entry.call_count, 2)
        select_source_task_entry.assert_any_call(
            [task_entry],
            find_record_output=session.ctx.find_record_output,
        )
        self.assertEqual(replay_records.call_count, 1)
        args, kwargs = replay_records.call_args
        self.assertEqual(args[0], session)
        self.assertEqual(args[1], source_records)
        self.assertEqual(args[2], replay_workflow.REPLAY_MODE_STANDARD)
        self.assertIn("全量模式已加载", args[3])
        self.assertIn("demo_tag", args[3])
        self.assertEqual(kwargs["display_tag"], "demo_tag")


class ReplayPrompterTests(unittest.TestCase):
    def test_select_source_task_entry_reprints_saved_find_record_output(self) -> None:
        task_entry = TaskEntry.from_manifest_parts(
            time="2026-04-15 12:00:00",
            name="demo_tag",
            paths=["/data/soc1/a.record"],
        )
        cached_output = "[1] demo_tag : 2026-04-15 12:00:00 [soc1]\n"

        with patch("builtins.input", side_effect=["1"]), patch(
            "sys.stdout",
            new_callable=StringIO,
        ) as stdout:
            selected = replay_prompter.select_source_task_entry(
                [task_entry],
                find_record_output=cached_output,
            )

        self.assertEqual(selected, task_entry)
        rendered = stdout.getvalue()
        self.assertIn("demo_tag", rendered)
        self.assertIn("2026-04-15 12:00:00", rendered)
        self.assertIn("[soc1]", rendered)


class RunnerTests(unittest.TestCase):
    def test_run_find_record_saves_terminal_output_to_context(self) -> None:
        ctx = SimpleNamespace(
            paths=SimpleNamespace(scripts_dir="scripts"),
            docker=SimpleNamespace(docker_scripts="/tmp"),
            find_record_output="",
        )
        runner = ScriptRunner(ctx)

        with patch.object(
            runner,
            "_run_script_with_terminal_capture",
            return_value="find output\n",
        ) as capture:
            runner.run_find_record()

        capture.assert_called_once_with("find_record.sh")
        self.assertEqual(ctx.find_record_output, "find output\n")


if __name__ == "__main__":
    unittest.main()
