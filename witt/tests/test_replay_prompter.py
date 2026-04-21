import unittest
from unittest.mock import patch

from core.models import LibraryEntry, ReplayRecord
from interface import prompter_replay as replay_prompter


class ReplayPrompterTests(unittest.TestCase):
    def test_filter_playback_entries_matches_tag_time_and_soc_keyword(self) -> None:
        library = [
            LibraryEntry(
                tag="demo_tag",
                time="2026-04-19 12:00:00",
                socs={"soc1": [ReplayRecord(path="/tmp/a.record", begin="2026-04-19T12:00:00", duration=10)]},
            ),
            LibraryEntry(
                tag="other_tag",
                time="2026-04-19 12:01:00",
                socs={"soc2": [ReplayRecord(path="/tmp/b.record", begin="2026-04-19T12:01:00", duration=10)]},
            ),
        ]

        filtered_entries = replay_prompter._filter_playback_entries(
            library,
            "demo soc1",
        )

        self.assertEqual([entry.tag for entry in filtered_entries], ["demo_tag"])

    def test_select_filtered_value_returns_selected_item_after_filter(self) -> None:
        render_calls = []
        user_inputs = iter(["/bar", "1"])

        with patch(
            "interface.prompter_replay.prompter.prompt_text",
            side_effect=lambda *args, **kwargs: next(user_inputs),
        ):
            with patch("interface.prompter_replay.ui.show_input_feedback") as show_input_feedback:
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
            "interface.prompter_replay.prompter.prompt_text",
            side_effect=lambda *args, **kwargs: next(user_inputs),
        ):
            with patch("interface.prompter_replay.ui.show_input_feedback") as show_input_feedback:
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
