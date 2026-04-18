import unittest

from interface import prompter


class TuiHelperTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
