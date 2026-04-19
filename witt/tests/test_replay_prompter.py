import unittest
from unittest.mock import patch

from interface import replay_prompter


class ReplayPrompterTests(unittest.TestCase):
    def test_select_filtered_value_returns_selected_item_after_filter(self) -> None:
        render_calls = []
        user_inputs = iter(["/bar", "1"])

        with patch(
            "interface.replay_prompter.prompter.prompt_text",
            side_effect=lambda *args, **kwargs: next(user_inputs),
        ):
            with patch("interface.replay_prompter.ui.show_input_feedback") as show_input_feedback:
                selected_item = replay_prompter._select_filtered_value(
                    ["foo", "bar", "baz"],
                    lambda items, keyword, total: render_calls.append(
                        (list(items), keyword, total)
                    ),
                    lambda items, keyword: [
                        item for item in items if keyword in item
                    ],
                    "选择条目",
                    "test_selection",
                    lambda items, selected_index: items[selected_index - 1],
                )

        self.assertEqual(selected_item, "bar")
        self.assertEqual(
            render_calls,
            [
                (["foo", "bar", "baz"], "", 3),
                (["bar"], "bar", 3),
            ],
        )
        show_input_feedback.assert_not_called()

    def test_select_filtered_value_handles_empty_filter_and_extra_choice(self) -> None:
        render_calls = []
        user_inputs = iter(["/missing", "1", "/", "0"])

        with patch(
            "interface.replay_prompter.prompter.prompt_text",
            side_effect=lambda *args, **kwargs: next(user_inputs),
        ):
            with patch("interface.replay_prompter.ui.show_input_feedback") as show_input_feedback:
                selected_value = replay_prompter._select_filtered_value(
                    [1],
                    lambda items, keyword, total: render_calls.append(
                        (list(items), keyword, total)
                    ),
                    lambda items, keyword: [
                        item for item in items if keyword in str(item)
                    ],
                    "选择历史",
                    "test_history_selection",
                    lambda items, selected_index: items[selected_index - 1],
                    render_when_unfiltered=False,
                    extra_choices={"0": 0},
                )

        self.assertEqual(selected_value, 0)
        self.assertEqual(
            render_calls,
            [
                ([], "missing", 1),
                ([], "missing", 1),
            ],
        )
        show_input_feedback.assert_called_once_with(
            "当前筛选结果为空，请调整关键字或输入 / 清空筛选",
        )


if __name__ == "__main__":
    unittest.main()
