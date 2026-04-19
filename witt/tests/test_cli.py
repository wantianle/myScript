import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from interface import cli
from interface import prompter


class CliTests(unittest.TestCase):
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
                opened = cli._open_in_editor(SimpleNamespace())

        self.assertFalse(opened)
        show_result_section.assert_called_once()

    def test_handle_config_command_rebuilds_session_on_success(self) -> None:
        config_path = "/tmp/demo-settings.yaml"
        old_session = SimpleNamespace(ctx=SimpleNamespace(config_path=config_path))
        new_session = object()

        with patch("interface.cli._open_in_editor", return_value=True):
            with patch("interface.cli.AppSession", return_value=new_session) as app_session:
                with patch("interface.cli.ui.show_notice_section") as show_notice_section:
                    returned_session = cli._handle_config_command(old_session)

        self.assertIs(returned_session, new_session)
        app_session.assert_called_once_with(config_path=config_path)
        show_notice_section.assert_called_once()

    def test_handle_history_subcommand_clear_clears_repository(self) -> None:
        history_repository = SimpleNamespace(clear=Mock())
        session = SimpleNamespace(replay_history_repository=history_repository)
        command_invocation = prompter.CommandInvocation(
            name="history",
            args=["clear"],
            raw="history clear",
        )

        with patch("interface.cli.prompter.get_confirm_input", return_value=True):
            with patch("interface.cli.ui.show_notice_section") as show_notice_section:
                handled = cli._handle_history_subcommand(session, command_invocation)

        self.assertTrue(handled)
        history_repository.clear.assert_called_once_with()
        show_notice_section.assert_called_once()

    def test_handle_history_subcommand_invalid_shows_result(self) -> None:
        session = SimpleNamespace()
        command_invocation = prompter.CommandInvocation(
            name="history",
            args=["unknown"],
            raw="history unknown",
        )

        with patch("interface.cli.ui.show_result_section") as show_result_section:
            handled = cli._handle_history_subcommand(session, command_invocation)

        self.assertTrue(handled)
        show_result_section.assert_called_once()


if __name__ == "__main__":
    unittest.main()
