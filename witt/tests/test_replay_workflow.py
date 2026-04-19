import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.models import ReplayHistoryEntry, ReplayRecord
from interface import replay_workflow


class ReplayWorkflowInterfaceTests(unittest.TestCase):
    def test_restore_environment_flow_returns_false_when_version_is_missing(self) -> None:
        session = SimpleNamespace(
            ctx=SimpleNamespace(logic=SimpleNamespace(version="")),
            runner=SimpleNamespace(
                restore_runtime_environment=Mock(),
                start_standard_replay_stack=Mock(),
                start_traffic_light_stack=Mock(),
            ),
        )

        with patch("interface.replay_workflow.config_prompter.get_json_input", return_value=""):
            with patch("interface.replay_workflow.ui.show_notice_section") as show_notice_section:
                restored = replay_workflow.restore_environment_flow(session, auto=False)

        self.assertFalse(restored)
        session.runner.restore_runtime_environment.assert_not_called()
        show_notice_section.assert_called_once()

    def test_try_build_issue_paths_returns_empty_when_value_error_raised(self) -> None:
        with patch(
            "interface.replay_workflow._build_issue_paths",
            side_effect=ValueError("bad path"),
        ):
            with patch("interface.replay_workflow.ui.show_notice_section") as show_notice_section:
                issue_paths = replay_workflow._try_build_issue_paths(
                    ["/tmp/demo.record"],
                    "20260419",
                    "XZB600001",
                )

        self.assertEqual(issue_paths, [])
        show_notice_section.assert_called_once()

    def test_validate_history_records_reports_missing_path(self) -> None:
        replay_records = [
            ReplayRecord(path="/tmp/not-found.record", begin="2026-04-19 12:00:00", duration=10)
        ]

        with patch("interface.replay_workflow.ui.show_result_section") as show_result_section:
            valid = replay_workflow._validate_history_records(replay_records)

        self.assertFalse(valid)
        show_result_section.assert_called_once()

    def test_replay_history_by_index_rejects_out_of_range_index(self) -> None:
        history_entry = ReplayHistoryEntry(
            created_at="2026-04-19 12:00:00",
            source_type="auto",
            replay_mode="standard",
            selection_label="demo",
            display_tag="demo_tag",
            issue_timestamp="2026-04-19 11:59:00",
            vehicle="XZB600001",
            target_date="20260419",
        )
        session = SimpleNamespace()

        with patch(
            "interface.replay_workflow.get_sorted_replay_history_entries",
            return_value=[history_entry],
        ):
            with patch("interface.replay_workflow.ui.show_result_section") as show_result_section:
                replayed = replay_workflow.replay_history_by_index(session, 2)

        self.assertFalse(replayed)
        show_result_section.assert_called_once()

    def test_auto_replay_flow_shows_result_when_library_is_empty(self) -> None:
        session = SimpleNamespace(
            player=SimpleNamespace(
                load_library=Mock(
                    return_value=SimpleNamespace(
                        cache_hit=False,
                        library=[],
                    )
                )
            ),
            ctx=SimpleNamespace(
                work_dir="/tmp/work",
                vehicle="XZB600001",
                target_date="20260419",
            ),
        )

        with patch("interface.replay_workflow.ui.show_result_section") as show_result_section:
            replay_workflow.auto_replay_flow(session)

        show_result_section.assert_called_once()

    def test_full_source_replay_flow_shows_result_when_task_entries_are_empty(self) -> None:
        session = SimpleNamespace()

        with patch("interface.replay_workflow.ui.show_result_section") as show_result_section:
            replay_workflow.full_source_replay_flow(session, [])

        show_result_section.assert_called_once()


if __name__ == "__main__":
    unittest.main()
