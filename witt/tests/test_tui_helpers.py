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

    def test_sort_completion_words_uses_natural_numeric_order(self) -> None:
        self.assertEqual(
            prompter._sort_completion_words(["10", "2", "1", "11", "3"]),
            ["1", "2", "3", "10", "11"],
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

    def test_show_option_choices_renders_default_marker(self) -> None:
        buffer = StringIO()
        console = Console(
            file=buffer,
            width=120,
            force_terminal=False,
            highlight=False,
            theme=ui._THEME,
        )
        previous_console = ui._CONSOLE
        try:
            ui._CONSOLE = console
            ui.show_option_choices(
                "SOC 选择",
                "选择要播放的 SOC",
                ["soc1", "soc2", "All"],
                default_index=3,
                summary="当前 Tag: demo_tag",
            )
        finally:
            ui._CONSOLE = previous_console

        rendered = buffer.getvalue()
        self.assertIn("SOC 选择", rendered)
        self.assertIn("当前 Tag: demo_tag", rendered)
        self.assertIn("候选项", rendered)
        self.assertIn("soc1", rendered)
        self.assertIn("All", rendered)
        self.assertIn("是", rendered)

    def test_show_config_section_renders_summary_and_hint(self) -> None:
        buffer = StringIO()
        console = Console(
            file=buffer,
            width=120,
            force_terminal=False,
            highlight=False,
            theme=ui._THEME,
        )
        previous_console = ui._CONSOLE
        try:
            ui._CONSOLE = console
            ui.show_config_section(
                "基本信息配置",
                "当前车号 XZB600001 | 当前日期 20260415",
                "先确认日期和车辆，后续查询、扫描和回播都基于这组信息",
            )
        finally:
            ui._CONSOLE = previous_console

        rendered = buffer.getvalue()
        self.assertIn("基本信息配置", rendered)
        self.assertIn("当前车号 XZB600001 | 当前日期 20260415", rendered)
        self.assertIn("先确认日期和车辆", rendered)

    def test_show_replay_section_renders_summary_and_hint(self) -> None:
        buffer = StringIO()
        console = Console(
            file=buffer,
            width=120,
            force_terminal=False,
            highlight=False,
            theme=ui._THEME,
        )
        previous_console = ui._CONSOLE
        try:
            ui._CONSOLE = console
            ui.show_replay_section(
                "播放倍速配置",
                "默认 1.0x，可设置 0.1 到 10x",
                "常用值: 0.5 / 1.0 / 1.5 / 2.0",
            )
        finally:
            ui._CONSOLE = previous_console

        rendered = buffer.getvalue()
        self.assertIn("播放倍速配置", rendered)
        self.assertIn("默认 1.0x，可设置 0.1 到 10x", rendered)
        self.assertIn("常用值: 0.5 / 1.0 / 1.5 / 2.0", rendered)

    def test_show_flow_section_renders_summary_and_hint(self) -> None:
        buffer = StringIO()
        console = Console(
            file=buffer,
            width=120,
            force_terminal=False,
            highlight=False,
            theme=ui._THEME,
        )
        previous_console = ui._CONSOLE
        try:
            ui._CONSOLE = console
            ui.show_flow_section(
                "切片模式",
                "查询 Record -> 选择 Tag -> 切片 -> 可选回播",
                "适合先做批量切片，再进入回播验证",
            )
        finally:
            ui._CONSOLE = previous_console

        rendered = buffer.getvalue()
        self.assertIn("切片模式", rendered)
        self.assertIn("查询 Record -> 选择 Tag -> 切片 -> 可选回播", rendered)
        self.assertIn("适合先做批量切片", rendered)

    def test_show_result_section_renders_details_and_next_step(self) -> None:
        buffer = StringIO()
        console = Console(
            file=buffer,
            width=120,
            force_terminal=False,
            highlight=False,
            theme=ui._THEME,
        )
        previous_console = ui._CONSOLE
        try:
            ui._CONSOLE = console
            ui.show_result_section(
                "切片结果",
                "所有同步任务已完成！",
                details=["已完成 3 个切片批次"],
                next_step="可立即进入回播，或返回 REPL 继续其他操作",
            )
        finally:
            ui._CONSOLE = previous_console

        rendered = buffer.getvalue()
        self.assertIn("切片结果", rendered)
        self.assertIn("所有同步任务已完成！", rendered)
        self.assertIn("已完成 3 个切片批次", rendered)
        self.assertIn("下一步", rendered)
        self.assertIn("可立即进入回播", rendered)

    def test_show_progress_section_renders_details_and_hint(self) -> None:
        buffer = StringIO()
        console = Console(
            file=buffer,
            width=120,
            force_terminal=False,
            highlight=False,
            theme=ui._THEME,
        )
        previous_console = ui._CONSOLE
        try:
            ui._CONSOLE = console
            ui.show_progress_section(
                "自动回播",
                "已扫描本地库",
                details=["/media/demo"],
                hint="正在构建回播条目列表",
            )
        finally:
            ui._CONSOLE = previous_console

        rendered = buffer.getvalue()
        self.assertIn("自动回播", rendered)
        self.assertIn("已扫描本地库", rendered)
        self.assertIn("/media/demo", rendered)
        self.assertIn("当前阶段", rendered)
        self.assertIn("正在构建回播条目列表", rendered)

if __name__ == "__main__":
    unittest.main()
