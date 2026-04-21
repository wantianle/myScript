import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, patch

from core.session import AppSession
from interface import cli
from interface import prompter


class CliTests(unittest.TestCase):
    def test_menu_renders_banner_on_startup(self) -> None:
        session = cast(AppSession, SimpleNamespace())
        prompt_session = SimpleNamespace(prompt=Mock(side_effect=EOFError))

        with patch("interface.cli.AppSession", return_value=session):
            with patch(
                "interface.cli.prompter.create_command_prompt_session",
                return_value=prompt_session,
            ):
                with patch("interface.cli.ui.print_banner") as print_banner:
                    with self.assertRaises(SystemExit):
                        cli.menu()

        print_banner.assert_called_once_with()

    def test_menu_clear_command_redraws_banner(self) -> None:
        session = cast(AppSession, SimpleNamespace())
        prompt_session = SimpleNamespace(
            prompt=Mock(side_effect=["clear", EOFError])
        )

        with patch("interface.cli.AppSession", return_value=session):
            with patch(
                "interface.cli.prompter.create_command_prompt_session",
                return_value=prompt_session,
            ):
                with patch("interface.cli.ui.print_banner") as print_banner:
                    with patch("interface.cli._clear_screen") as clear_screen:
                        with self.assertRaises(SystemExit):
                            cli.menu()

        clear_screen.assert_called_once_with()
        self.assertEqual(print_banner.call_count, 2)

    def test_validate_command_args_rejects_extra_args_for_intent_command(self) -> None:
        command_invocation = prompter.CommandInvocation(
            name="slice",
            args=["extra"],
            raw="slice extra",
        )

        with patch("interface.cli.ui.show_input_feedback") as show_input_feedback:
            valid = cli._validate_command_args(command_invocation)

        self.assertFalse(valid)
        show_input_feedback.assert_called_once()

    def test_open_in_editor_returns_false_when_no_editor_available(self) -> None:
        with patch("interface.cli._resolve_editor_command", return_value=None):
            with patch("interface.cli.ui.show_result_section") as show_result_section:
                opened = cli._open_in_editor(Path("/tmp/demo-settings.yaml"))

        self.assertFalse(opened)
        show_result_section.assert_called_once()

    def test_handle_config_command_rebuilds_session_on_success(self) -> None:
        config_path = Path("/tmp/demo-settings.yaml")
        old_session = cast(
            AppSession,
            SimpleNamespace(ctx=SimpleNamespace(config_path=config_path)),
        )
        new_session = cast(AppSession, SimpleNamespace())

        with patch("interface.cli._open_in_editor", return_value=True):
            with patch("interface.cli.AppSession", return_value=new_session) as app_session:
                with patch("interface.cli.ui.show_notice_section") as show_notice_section:
                    returned_session = cli._handle_config_command(old_session)

        self.assertIs(returned_session, new_session)
        app_session.assert_called_once_with(config_path=config_path)
        show_notice_section.assert_called_once()

    def test_handle_history_subcommand_clear_clears_repository(self) -> None:
        save_history = Mock()
        history_repository = SimpleNamespace(save=save_history)
        session = cast(
            AppSession,
            SimpleNamespace(replay_history_repository=history_repository),
        )
        command_invocation = prompter.CommandInvocation(
            name="history",
            args=["clear"],
            raw="history clear",
        )

        with patch("interface.cli.prompter.get_confirm_input", return_value=True):
            with patch("interface.cli.ui.show_notice_section") as show_notice_section:
                handled = cli._handle_history_subcommand(session, command_invocation)

        self.assertTrue(handled)
        save_history.assert_called_once_with([])
        show_notice_section.assert_called_once()

    def test_handle_history_subcommand_invalid_shows_result(self) -> None:
        session = cast(AppSession, SimpleNamespace())
        command_invocation = prompter.CommandInvocation(
            name="history",
            args=["unknown"],
            raw="history unknown",
        )

        with patch("interface.cli.ui.show_result_section") as show_result_section:
            handled = cli._handle_history_subcommand(session, command_invocation)

        self.assertTrue(handled)
        show_result_section.assert_called_once()

    def test_handle_history_subcommand_last_replays_latest_entry(self) -> None:
        session = cast(AppSession, SimpleNamespace())
        command_invocation = prompter.CommandInvocation(
            name="history",
            args=["last"],
            raw="history last",
        )

        with patch("interface.cli.replay_workflow.replay_latest_history_entry") as replay_latest_history_entry:
            handled = cli._handle_history_subcommand(session, command_invocation)

        self.assertTrue(handled)
        replay_latest_history_entry.assert_called_once_with(session)

    def test_handle_history_subcommand_numeric_replays_by_index(self) -> None:
        session = cast(AppSession, SimpleNamespace())
        command_invocation = prompter.CommandInvocation(
            name="history",
            args=["3"],
            raw="history 3",
        )

        with patch("interface.cli.replay_workflow.replay_history_by_index") as replay_history_by_index:
            handled = cli._handle_history_subcommand(session, command_invocation)

        self.assertTrue(handled)
        replay_history_by_index.assert_called_once_with(session, 3)


if __name__ == "__main__":
    unittest.main()
