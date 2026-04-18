from io import StringIO
import unittest

from interface import prompter
from interface import ui
from rich.console import Console


class TuiHelperTests(unittest.TestCase):
    def _render(self, renderable) -> str:
        buffer = StringIO()
        console = Console(
            file=buffer,
            width=120,
            force_terminal=False,
            highlight=False,
            theme=ui._THEME,
        )
        console.print(renderable)
        return buffer.getvalue()

    def test_matches_search_keyword_supports_multiple_tokens(self) -> None:
        matched = prompter.matches_search_keyword(
            "20260415 demo",
            ["demo_tag", "20260415", "soc1 soc2"],
        )

        self.assertTrue(matched)
        self.assertFalse(
            prompter.matches_search_keyword(
                "20260415 missing",
                ["demo_tag", "20260415", "soc1 soc2"],
            )
        )

    def test_parse_index_expression_supports_range_and_exclude(self) -> None:
        self.assertEqual(
            prompter.parse_index_expression("1,3-4", 5),
            [1, 3, 4],
        )
        self.assertEqual(
            prompter.parse_index_expression("0 2-4", 5),
            [1, 5],
        )

    def test_selector_state_panel_shows_filter_summary_and_empty_state(self) -> None:
        rendered = self._render(
            ui._build_selector_state_panel(
                "查询结果",
                "Tag",
                0,
                3,
                "demo",
            )
        )

        self.assertIn("当前筛选", rendered)
        self.assertIn("/demo", rendered)
        self.assertIn("0/3", rendered)
        self.assertIn("输入 /关键字 筛选", rendered)
        self.assertIn("当前筛选没有匹配结果", rendered)

    def test_selector_empty_panel_guides_user_to_clear_filter(self) -> None:
        rendered = self._render(
            ui._build_selector_empty_panel(
                "回放库",
                "回播条目",
                "soc2",
            )
        )

        self.assertIn("没有匹配到回播条目", rendered)
        self.assertIn("当前筛选: /soc2", rendered)
        self.assertIn("输入新的 /关键字，或输入 / 清空筛选", rendered)

    def test_page_intro_panel_includes_summary_and_hint(self) -> None:
        rendered = self._render(
            ui._build_page_intro_panel(
                "命令帮助",
                "查看命令: replay",
                "输入 help <command> 查看单个命令，输入 clear 清屏",
            )
        )

        self.assertIn("命令帮助", rendered)
        self.assertIn("查看命令: replay", rendered)
        self.assertIn("输入 help <command> 查看单个命令", rendered)


if __name__ == "__main__":
    unittest.main()
