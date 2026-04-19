import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, patch

from core.errors import ScriptExecutionError
from core.models import ReplayHistoryEntry, ReplayRecord, TaskEntry
from core.session import AppSession
from interface import replay_workflow


class ReplayWorkflowInterfaceTests(unittest.TestCase):
    def test_restore_environment_flow_returns_false_when_version_is_missing(self) -> None:
        restore_runtime_environment = Mock()
        session = cast(
            AppSession,
            SimpleNamespace(
                ctx=SimpleNamespace(logic=SimpleNamespace(version="")),
                runtime=SimpleNamespace(
                    restore_runtime_environment=restore_runtime_environment,
                    start_standard_replay_stack=Mock(),
                    start_traffic_light_stack=Mock(),
                ),
            ),
        )

        with patch("interface.replay_workflow.config_prompter.get_json_input", return_value=""):
            with patch("interface.replay_workflow.ui.show_notice_section") as show_notice_section:
                restored = replay_workflow.restore_environment_flow(session, auto=False)

        self.assertFalse(restored)
        restore_runtime_environment.assert_not_called()
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

    def test_restore_environment_flow_shows_result_when_restore_script_fails(self) -> None:
        session = cast(
            AppSession,
            SimpleNamespace(
                ctx=SimpleNamespace(logic=SimpleNamespace(version="/tmp/version.json")),
                runtime=SimpleNamespace(
                    restore_runtime_environment=Mock(
                        side_effect=ScriptExecutionError(
                            "runtime_environment",
                            "文件不存在: /tmp/version.json",
                            details=["运行环境同步退出状态码: 1"],
                        )
                    ),
                    start_standard_replay_stack=Mock(),
                    start_traffic_light_stack=Mock(),
                ),
            ),
        )

        with patch("interface.replay_workflow.ui.show_result_section") as show_result_section:
            restored = replay_workflow.restore_environment_flow(session, auto=True)

        self.assertFalse(restored)
        show_result_section.assert_called_once()

    def test_restore_environment_flow_uses_page_style_prompt_for_standard_stack(self) -> None:
        start_standard_replay_stack = Mock()
        session = cast(
            AppSession,
            SimpleNamespace(
                ctx=SimpleNamespace(logic=SimpleNamespace(version="/tmp/version.json")),
                runtime=SimpleNamespace(
                    restore_runtime_environment=Mock(),
                    start_standard_replay_stack=start_standard_replay_stack,
                    start_traffic_light_stack=Mock(),
                ),
            ),
        )

        with patch(
            "interface.replay_workflow.ui.show_replay_section"
        ) as show_replay_section:
            with patch(
                "interface.replay_workflow.prompter.get_confirm_input",
                return_value=True,
            ) as get_confirm_input:
                restored = replay_workflow.restore_environment_flow(
                    session,
                    auto=True,
                    replay_mode=replay_workflow.REPLAY_MODE_STANDARD,
                )

        self.assertTrue(restored)
        show_replay_section.assert_called_once()
        get_confirm_input.assert_called_once_with("是否打开Dreamview和Multiviz工具？")
        start_standard_replay_stack.assert_called_once_with()

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
        session = cast(AppSession, SimpleNamespace())

        with patch(
            "interface.replay_workflow.get_sorted_replay_history_entries",
            return_value=[history_entry],
        ):
            with patch("interface.replay_workflow.ui.show_result_section") as show_result_section:
                replayed = replay_workflow.replay_history_by_index(session, 2)

        self.assertFalse(replayed)
        show_result_section.assert_called_once()

    def test_replay_latest_history_entry_returns_false_when_history_is_empty(self) -> None:
        session = cast(AppSession, SimpleNamespace())

        with patch(
            "interface.replay_workflow.get_sorted_replay_history_entries",
            return_value=[],
        ):
            with patch("interface.replay_workflow.ui.show_result_section") as show_result_section:
                replayed = replay_workflow.replay_latest_history_entry(session)

        self.assertFalse(replayed)
        show_result_section.assert_called_once()

    def test_replay_history_entry_rejects_invalid_history_paths(self) -> None:
        history_entry = ReplayHistoryEntry(
            created_at="2026-04-19 12:00:00",
            source_type="auto",
            replay_mode="standard",
            selection_label="demo",
            display_tag="demo_tag",
            issue_timestamp="2026-04-19 11:59:00",
            vehicle="XZB600001",
            target_date="20260419",
            records=[
                ReplayRecord(
                    path="/tmp/not-found.record",
                    begin="2026-04-19 12:00:00",
                    duration=10,
                )
            ],
        )
        session = cast(AppSession, SimpleNamespace())

        with patch("interface.replay_workflow.ui.show_result_section") as show_result_section:
            replayed = replay_workflow.replay_history_entry(session, history_entry)

        self.assertFalse(replayed)
        show_result_section.assert_called_once()

    def test_auto_replay_flow_shows_result_when_library_is_empty(self) -> None:
        session = cast(
            AppSession,
            SimpleNamespace(
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
            ),
        )

        with patch("interface.replay_workflow.ui.show_result_section") as show_result_section:
            replay_workflow.auto_replay_flow(session)

        show_result_section.assert_called_once()

    def test_auto_replay_flow_only_shows_library_progress_once(self) -> None:
        selected_tag = SimpleNamespace(
            tag="demo_tag",
            time="2026-04-19 12:00:00",
        )
        target_records = [
            ReplayRecord(
                path="/tmp/demo.record",
                begin=datetime(2026, 4, 19, 11, 59, 50),
                duration=20,
            )
        ]
        session = cast(
            AppSession,
            SimpleNamespace(
                player=SimpleNamespace(
                    load_library=Mock(
                        side_effect=[
                            SimpleNamespace(cache_hit=False, library=["demo"]),
                            SimpleNamespace(cache_hit=True, library=["demo"]),
                        ]
                    )
                ),
                ctx=SimpleNamespace(
                    work_dir="/tmp/work",
                    vehicle="XZB600001",
                    target_date="20260419",
                ),
            ),
        )

        with patch(
            "interface.replay_workflow.replay_prompter.select_playback_entry",
            side_effect=[selected_tag, None],
        ):
            with patch(
                "interface.replay_workflow.replay_prompter.select_replay_records",
                return_value=target_records,
            ):
                with patch("interface.replay_workflow.ui.show_progress_section") as show_progress_section:
                    with patch("interface.replay_workflow._update_playback_blacklist"):
                        with patch("interface.replay_workflow._replay_records"):
                            replay_workflow.auto_replay_flow(session)

        show_progress_section.assert_called_once()

    def test_full_source_replay_flow_shows_result_when_task_entries_are_empty(self) -> None:
        session = cast(AppSession, SimpleNamespace())

        with patch("interface.replay_workflow.ui.show_result_section") as show_result_section:
            replay_workflow.full_source_replay_flow(session, [])

        show_result_section.assert_called_once()

    def test_full_source_replay_flow_replays_without_preview_confirmation(self) -> None:
        task_entry = TaskEntry(
            time="2026-04-19 12:00:00",
            name="demo_tag",
            soc_paths={"soc1": ["/tmp/a"], "soc2": []},
            paths=["/tmp/a"],
            id="01",
        )
        source_records = [
            ReplayRecord(
                path="/tmp/demo.record",
                begin=datetime(2026, 4, 19, 11, 59, 50),
                duration=20,
            )
        ]
        session = cast(AppSession, SimpleNamespace())

        with patch(
            "interface.replay_workflow.replay_prompter.select_source_task_entry",
            side_effect=[task_entry, None],
        ):
            with patch(
                "interface.replay_workflow._build_source_replay_records",
                return_value=source_records,
            ):
                with patch("interface.replay_workflow._update_playback_blacklist") as update_blacklist:
                    with patch("interface.replay_workflow._replay_records") as replay_records:
                        replay_workflow.full_source_replay_flow(session, [task_entry])

        update_blacklist.assert_called_once()
        replay_records.assert_called_once()

    def test_auto_replay_flow_replays_without_preview_confirmation(self) -> None:
        selected_tag = SimpleNamespace(
            tag="demo_tag",
            time="2026-04-19 12:00:00",
        )
        target_records = [
            ReplayRecord(
                path="/tmp/demo.record",
                begin=datetime(2026, 4, 19, 11, 59, 50),
                duration=20,
            )
        ]
        session = cast(
            AppSession,
            SimpleNamespace(
                player=SimpleNamespace(
                    load_library=Mock(
                        return_value=SimpleNamespace(
                            cache_hit=False,
                            library=["demo"],
                        )
                    )
                ),
                ctx=SimpleNamespace(
                    work_dir="/tmp/work",
                    vehicle="XZB600001",
                    target_date="20260419",
                ),
            ),
        )

        with patch(
            "interface.replay_workflow.replay_prompter.select_playback_entry",
            side_effect=[selected_tag, None],
        ):
            with patch(
                "interface.replay_workflow.replay_prompter.select_replay_records",
                return_value=target_records,
            ):
                with patch("interface.replay_workflow._update_playback_blacklist") as update_blacklist:
                    with patch("interface.replay_workflow._replay_records") as replay_records:
                        replay_workflow.auto_replay_flow(session)

        update_blacklist.assert_called_once()
        replay_records.assert_called_once()

    def test_manual_replay_paths_flow_replays_without_preview_confirmation(self) -> None:
        session = cast(
            AppSession,
            SimpleNamespace(
                recorder=SimpleNamespace(
                    get_info=Mock(
                        side_effect=[
                            SimpleNamespace(
                                begin=datetime(2026, 4, 19, 12, 0, 0),
                                end=datetime(2026, 4, 19, 12, 0, 10),
                            ),
                            SimpleNamespace(
                                begin=datetime(2026, 4, 19, 12, 0, 0),
                                end=datetime(2026, 4, 19, 12, 0, 10),
                            ),
                        ]
                    )
                ),
            ),
        )
        paths = [Path("/tmp/demo.record")]

        with patch("interface.replay_workflow.termios.tcflush"):
            with patch("interface.replay_workflow._update_playback_blacklist") as update_blacklist:
                with patch("interface.replay_workflow._replay_records") as replay_records:
                    replay_workflow.manual_replay_paths_flow(session, paths)

        update_blacklist.assert_called_once()
        replay_records.assert_called_once()

    def test_replay_history_entry_replays_without_preview_confirmation(self) -> None:
        history_entry = ReplayHistoryEntry(
            created_at="2026-04-19 12:00:00",
            source_type="auto",
            replay_mode="standard",
            selection_label="demo",
            display_tag="demo_tag",
            issue_timestamp="2026-04-19 11:59:00",
            vehicle="XZB600001",
            target_date="20260419",
            records=[
                ReplayRecord(
                    path=__file__,
                    begin="2026-04-19 12:00:00",
                    duration=10,
                )
            ],
        )
        init_logging = Mock()
        session = cast(
            AppSession,
            SimpleNamespace(
                init_logging=init_logging,
                ctx=SimpleNamespace(logic=SimpleNamespace()),
            ),
        )

        with patch("interface.replay_workflow._replay_records") as replay_records:
            replayed = replay_workflow.replay_history_entry(session, history_entry)

        self.assertTrue(replayed)
        init_logging.assert_called_once_with()
        replay_records.assert_called_once()


if __name__ == "__main__":
    unittest.main()
