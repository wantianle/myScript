import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, patch

from core.models import ReplayHistoryEntry, ReplayRecord, TaskEntry
from core.session import AppSession
from interface import workflow_replay as replay_workflow
from interface import workflow


class FlowIntegrationTests(unittest.TestCase):
    def test_scan_select_entry_then_replay(self) -> None:
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
        setup_logger = Mock()
        session = cast(
            AppSession,
            SimpleNamespace(
                ctx=SimpleNamespace(
                    work_dir="/tmp/work",
                    logic=SimpleNamespace(
                        vehicle="XZB600001",
                        target_date="20260419",
                    ),
                    setup_logger=setup_logger,
                ),
                player=SimpleNamespace(
                    load_library=Mock(
                        return_value=SimpleNamespace(
                            cache_hit=False,
                            library=["demo"],
                        )
                    )
                ),
            ),
        )

        with patch("interface.workflow.prompter_config.get_basic_params") as get_basic_params:
            with patch("interface.workflow.prompter_config.update_dest_root") as update_dest_root:
                with patch(
                    "interface.workflow_replay.prompter_replay.select_playback_entry",
                    side_effect=[selected_tag, None],
                ):
                    with patch(
                        "interface.workflow_replay.prompter_replay.select_replay_records",
                        return_value=target_records,
                    ):
                        with patch("interface.workflow_replay._update_playback_blacklist") as update_blacklist:
                            with patch("interface.workflow_replay._replay_records") as replay_records:
                                workflow.auto_replay_progress(session)

        get_basic_params.assert_called_once_with(session.ctx)
        update_dest_root.assert_called_once()
        update_blacklist.assert_called_once_with(
            session,
            target_records,
            replay_workflow.REPLAY_MODE_STANDARD,
        )
        replay_records.assert_called_once()

    def test_manual_then_replay(self) -> None:
        setup_logger = Mock()
        session = cast(
            AppSession,
            SimpleNamespace(
                ctx=SimpleNamespace(setup_logger=setup_logger),
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
        manual_paths = [Path("/tmp/demo.record")]

        with patch("interface.workflow.prompter_config.get_basic_params") as get_basic_params:
            with patch(
                "interface.workflow_replay.prompter_replay.get_manual_replay_paths",
                return_value=manual_paths,
            ):
                with patch("interface.workflow_replay.termios.tcflush"):
                    with patch("interface.workflow_replay._update_playback_blacklist") as update_blacklist:
                        with patch("interface.workflow_replay._replay_records") as replay_records:
                            workflow.manual_replay_progress(session)

        get_basic_params.assert_called_once_with(session.ctx)
        setup_logger.assert_called_once_with()
        update_blacklist.assert_called_once()
        replay_records.assert_called_once()

    def test_history_then_replay(self) -> None:
        history_entry = ReplayHistoryEntry(
            created_at="2026-04-19 12:00:00",
            source_type="auto",
            replay_mode="standard",
            selection_label="demo | soc1 | 1 files",
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
        setup_logger = Mock()
        session = cast(
            AppSession,
            SimpleNamespace(
                ctx=SimpleNamespace(
                    logic=SimpleNamespace(),
                    setup_logger=setup_logger,
                ),
            ),
        )

        with patch(
            "interface.workflow_replay.get_sorted_replay_history_entries",
            return_value=[history_entry],
        ):
            with patch("interface.workflow_replay.ui.browse_replay_history") as browse_replay_history:
                with patch(
                    "interface.workflow_replay.prompter_replay.select_replay_history_index",
                    return_value=1,
                ):
                    with patch("interface.workflow_replay._replay_records") as replay_records:
                        workflow.replay_history_progress(session)

        browse_replay_history.assert_called_once_with([history_entry])
        setup_logger.assert_called_once_with()
        replay_records.assert_called_once()

    def test_traffic_then_restore_environment_then_replay(self) -> None:
        setup_logger = Mock()
        restore_runtime_environment = Mock()
        start_standard_replay_stack = Mock()
        start_traffic_light_stack = Mock()
        execute_interactive = Mock()
        session = cast(
            AppSession,
            SimpleNamespace(
                ctx=SimpleNamespace(
                    logic=SimpleNamespace(version=""),
                    setup_logger=setup_logger,
                ),
                runtime=SimpleNamespace(
                    restore_runtime_environment=restore_runtime_environment,
                    start_standard_replay_stack=start_standard_replay_stack,
                    start_traffic_light_stack=start_traffic_light_stack,
                ),
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
                player=SimpleNamespace(
                    build_playback_plan=Mock(
                        return_value=SimpleNamespace(
                            display_tag="demo_tag",
                            duration=10,
                            rate=1.0,
                            command="cyber_recorder play -r 1",
                        )
                    )
                ),
                executor=SimpleNamespace(execute_interactive=execute_interactive),
            ),
        )
        manual_paths = [Path("/tmp/demo.record")]

        with patch(
            "interface.workflow_replay.prompter.get_confirm_input",
            side_effect=[True, True, True, False],
        ):
            with patch("interface.workflow_replay.prompter_config.get_json_input", return_value="/tmp/version.json"):
                with patch("interface.workflow_replay.prompter_replay.get_playback_range", return_value=(0, 0)):
                    with patch("interface.workflow_replay.prompter_replay.get_playback_rate", return_value=1.0):
                        with patch("interface.workflow.prompter_config.get_basic_params") as get_basic_params:
                            with patch("interface.workflow_replay.prompter_replay.get_manual_replay_paths", return_value=manual_paths):
                                with patch("interface.workflow_replay.termios.tcflush"):
                                    with patch("interface.workflow_replay.prompter_channel.get_paths_channels", return_value=[]):
                                        with patch("interface.workflow_replay._collect_issue_marker", return_value=None):
                                            with patch("interface.workflow_replay._post_replay_issue_draft"):
                                                replay_workflow.traffic_light_replay_flow(session)

        get_basic_params.assert_called_once_with(session.ctx)
        setup_logger.assert_called_once_with()
        restore_runtime_environment.assert_called_once_with()
        start_standard_replay_stack.assert_called_once_with()
        start_traffic_light_stack.assert_called_once_with()
        execute_interactive.assert_called_once_with("cyber_recorder play -r 1")


if __name__ == "__main__":
    unittest.main()
