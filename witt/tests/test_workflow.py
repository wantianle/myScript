import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.models import TaskEntry
from interface import workflow


class WorkflowTests(unittest.TestCase):
    def test_task_entry_search_values_contains_soc_and_count_fields(self) -> None:
        task_entry = TaskEntry(
            time="2026-04-19 12:00:00",
            name="demo_tag",
            soc_paths={"soc1": ["/tmp/a"], "soc2": []},
            paths=["/tmp/a"],
            id="01",
        )

        values = workflow._task_entry_search_values(task_entry)

        self.assertIn("01", values)
        self.assertIn("soc1", values)
        self.assertIn("1", values)

    def test_load_task_entries_shows_result_when_manifest_is_empty(self) -> None:
        session = SimpleNamespace(ctx=SimpleNamespace(manifest_path="/tmp/manifest"))

        with patch("interface.workflow.search_flow") as search_flow:
            with patch("interface.workflow.parser.parse_manifest", return_value=[]):
                with patch("interface.workflow.ui.show_result_section") as show_result_section:
                    task_entries = workflow._load_task_entries(session)

        self.assertEqual(task_entries, [])
        search_flow.assert_called_once()
        show_result_section.assert_called_once()

    def test_slice_progress_returns_when_no_task_selected(self) -> None:
        session = SimpleNamespace(
            record_downloader=SimpleNamespace(plan_download=Mock()),
        )
        task_entry = TaskEntry(
            time="2026-04-19 12:00:00",
            name="demo_tag",
            soc_paths={"soc1": ["/tmp/a"], "soc2": []},
            paths=["/tmp/a"],
            id="01",
        )

        with patch("interface.workflow._load_task_entries", return_value=[task_entry]):
            with patch("interface.workflow.prompter.get_selected_indices", return_value=[]):
                workflow.slice_progress(session)

        session.record_downloader.plan_download.assert_not_called()

    def test_slice_progress_shows_result_when_download_plan_is_empty(self) -> None:
        task_entry = TaskEntry(
            time="2026-04-19 12:00:00",
            name="demo_tag",
            soc_paths={"soc1": ["/tmp/a"], "soc2": []},
            paths=["/tmp/a"],
            id="01",
        )
        session = SimpleNamespace(
            ctx=SimpleNamespace(logic=SimpleNamespace(blacklist=[])),
            record_downloader=SimpleNamespace(
                plan_download=Mock(
                    return_value=SimpleNamespace(total_files=0, skipped_batches=[])
                ),
            ),
        )

        with patch("interface.workflow._load_task_entries", return_value=[task_entry]):
            with patch("interface.workflow.prompter.get_selected_indices", return_value=[task_entry]):
                with patch("interface.workflow.channel_prompter.get_tasks_channels", return_value=[]):
                    with patch("interface.workflow.ui.show_result_section") as show_result_section:
                        workflow.slice_progress(session)

        show_result_section.assert_called_once()

    def test_full_source_progress_shows_result_when_no_valid_paths_exist(self) -> None:
        invalid_task = TaskEntry(
            time="2026-04-19 12:00:00",
            name="demo_tag",
            soc_paths={"soc1": [], "soc2": []},
            paths=[],
            id="01",
        )
        session = SimpleNamespace()

        with patch("interface.workflow._load_task_entries", return_value=[invalid_task]):
            with patch("interface.workflow.ui.show_result_section") as show_result_section:
                workflow.full_source_progress(session)

        show_result_section.assert_called_once()

    def test_search_flow_calls_prompt_collectors_and_runner(self) -> None:
        session = SimpleNamespace(
            ctx=SimpleNamespace(),
            init_logging=Mock(),
            runner=SimpleNamespace(run_find_record=Mock()),
        )

        with patch("interface.workflow.config_prompter.get_basic_params") as get_basic_params:
            with patch("interface.workflow.config_prompter.get_source_path_params") as get_source_path_params:
                with patch("interface.workflow.config_prompter.get_export_path_params") as get_export_path_params:
                    with patch("interface.workflow.config_prompter.get_split_params") as get_split_params:
                        workflow.search_flow(session, need_export_path=True)

        get_basic_params.assert_called_once_with(session.ctx)
        get_source_path_params.assert_called_once()
        get_export_path_params.assert_called_once_with(session.ctx)
        get_split_params.assert_called_once_with(session.ctx)
        session.init_logging.assert_called_once_with()
        session.runner.run_find_record.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
