import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from interface import config_prompter


class ConfigPrompterTests(unittest.TestCase):
    def test_is_valid_vehicle_name_matches_expected_pattern(self) -> None:
        self.assertTrue(config_prompter._is_valid_vehicle_name("XZB600001"))
        self.assertFalse(config_prompter._is_valid_vehicle_name("ABC123"))

    def test_get_vehicle_name_retries_until_input_is_valid(self) -> None:
        with patch(
            "interface.config_prompter.prompter.prompt_text",
            side_effect=["bad", "xzb600001"],
        ):
            with patch("interface.config_prompter.ui.show_input_feedback") as show_input_feedback:
                vehicle_name = config_prompter.get_vehicle_name("")

        self.assertEqual(vehicle_name, "XZB600001")
        show_input_feedback.assert_called_once()

    def test_get_split_params_retries_until_window_is_valid(self) -> None:
        ctx = SimpleNamespace(
            logic=SimpleNamespace(before=1, after=1),
        )

        with patch(
            "interface.config_prompter.prompter.get_int_input",
            side_effect=[-1, 5, 5, 5],
        ):
            with patch("interface.config_prompter.ui.show_input_feedback") as show_input_feedback:
                config_prompter.get_split_params(ctx)

        self.assertEqual(ctx.logic.before, 5)
        self.assertEqual(ctx.logic.after, 5)
        show_input_feedback.assert_called_once_with("before 不能小于 0")

    def test_get_split_params_uses_replay_window_labels_when_requested(self) -> None:
        ctx = SimpleNamespace(
            logic=SimpleNamespace(before=1, after=1),
        )

        with patch(
            "interface.config_prompter.prompter.get_int_input",
            side_effect=[5, 6],
        ) as get_int_input:
            with patch("interface.config_prompter.ui.show_config_section") as show_config_section:
                config_prompter.get_split_params(ctx, "回播窗口")

        self.assertEqual(ctx.logic.before, 5)
        self.assertEqual(ctx.logic.after, 6)
        show_config_section.assert_called_once()
        self.assertEqual(get_int_input.call_args_list[0][0][0], "回播开始前多少秒")
        self.assertEqual(get_int_input.call_args_list[1][0][0], "回播结束后多少秒")

    def test_get_json_input_retries_after_empty_input(self) -> None:
        with tempfile.NamedTemporaryFile() as temp_file:
            with patch(
                "interface.config_prompter.prompter.prompt_text",
                side_effect=["", temp_file.name],
            ):
                with patch("interface.config_prompter.ui.show_input_feedback") as show_input_feedback:
                    result = config_prompter.get_json_input()

        self.assertEqual(result, temp_file.name)
        show_input_feedback.assert_called_once_with("输入为空，请重新输入")

    def test_get_json_input_returns_empty_on_keyboard_interrupt(self) -> None:
        with patch(
            "interface.config_prompter.prompter.prompt_text",
            side_effect=KeyboardInterrupt,
        ):
            with patch("interface.config_prompter.ui.show_notice_section") as show_notice_section:
                result = config_prompter.get_json_input()

        self.assertEqual(result, "")
        show_notice_section.assert_called_once()


if __name__ == "__main__":
    unittest.main()
