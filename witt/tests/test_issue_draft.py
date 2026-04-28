import tempfile
import unittest
from pathlib import Path

from core.issue_draft import (
    DEFAULT_ISSUE_DESCRIPTION,
    IssueDraft,
    render_issue_markdown,
    save_issue_draft,
    build_issue_title_from_vmc,
    format_issue_data_path,
    load_version_text,
)


class IssueDraftTests(unittest.TestCase):
    def test_render_issue_markdown_includes_replay_fields(self) -> None:
        issue_draft = IssueDraft(
            tag_text="demo_tag",
            vehicle="XZB600013",
            target_date="20260416",
            tag_time_text="2026-04-16 12:00:00",
            playback_command=(
                "cyber_recorder play -l \\\n"
                "  -s 5 \\\n"
                "  -r 2 \\\n"
                '  -b "2026-04-16 12:00:00" \\\n'
                '  -e "2026-04-16 12:00:10" \\\n'
                "  -f /tmp/a.record"
            ),
            version_text='{"version":"demo"}',
            playback_rate=2.0,
            playback_range_text="5",
            playback_channels=["/apollo/foo"],
            suggested_title="[E171-模块-XZB600013]demo_tag",
        )

        markdown_text = render_issue_markdown(issue_draft)

        self.assertIn("demo_tag", markdown_text)
        self.assertIn("[E171-模块-XZB600013]demo_tag", markdown_text)
        self.assertIn("XZB600013 | 2026-04-16 12:00:00", markdown_text)
        self.assertIn("cyber_recorder play -l \\", markdown_text)
        self.assertIn("  -s 5 \\", markdown_text)
        self.assertIn("  -r 2 \\", markdown_text)
        self.assertNotIn("回播参数", markdown_text)
        self.assertNotIn("channels(-k):", markdown_text)
        self.assertNotIn("数据路径", markdown_text)

    def test_render_issue_markdown_falls_back_to_target_date_when_tag_time_missing(self) -> None:
        issue_draft = IssueDraft(
            tag_text="demo_tag",
            vehicle="XZB600013",
            target_date="20260416",
            playback_command="cyber_recorder play -r 1",
        )

        markdown_text = render_issue_markdown(issue_draft)

        self.assertIn("XZB600013 | 20260416", markdown_text)

    def test_render_issue_markdown_formats_compact_tag_timestamp(self) -> None:
        issue_draft = IssueDraft(
            tag_text="demo_tag",
            vehicle="XZB600013",
            target_date="20260416",
            tag_time_text="20260416_120000",
            playback_command="cyber_recorder play -r 1",
        )

        markdown_text = render_issue_markdown(issue_draft)

        self.assertIn("XZB600013 | 2026-04-16 12:00:00", markdown_text)

    def test_build_issue_title_from_vmc_uses_vehicle_fields_and_tag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            vmc_path = Path(tmpdir) / "vmc.sh"
            vmc_path.write_text(
                "\n".join(
                    [
                        'MDRIVE_VEHICLE_MODEL="E171"',
                        'MDRIVE_VEHICLE_NAME="XZB600013"',
                    ]
                ),
                encoding="utf-8",
            )

            suggested_title = build_issue_title_from_vmc(vmc_path, "demo_tag")

        self.assertEqual(suggested_title, "[E171-模块-XZB600013]demo_tag")

    def test_build_issue_title_from_vmc_trims_vehicle_model_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            vmc_path = Path(tmpdir) / "vmc.sh"
            vmc_path.write_text(
                "\n".join(
                    [
                        'MDRIVE_VEHICLE_MODEL="AB6_HW3"',
                        'MDRIVE_VEHICLE_NAME="XZB600013"',
                    ]
                ),
                encoding="utf-8",
            )

            suggested_title = build_issue_title_from_vmc(vmc_path, "demo_tag")

        self.assertEqual(suggested_title, "[AB6-模块-XZB600013]demo_tag")

    def test_build_issue_title_from_vmc_falls_back_when_fields_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            vmc_path = Path(tmpdir) / "vmc.sh"
            vmc_path.write_text(
                'MDRIVE_VEHICLE_MODEL="E171"\n',
                encoding="utf-8",
            )

            suggested_title = build_issue_title_from_vmc(vmc_path, "demo_tag")

        self.assertEqual(suggested_title, "[车型-模块-车号]问题简述")

    def test_save_issue_draft_writes_into_work_dir_issues(self) -> None:
        issue_draft = IssueDraft(
            tag_text="demo_tag",
            vehicle="XZB600013",
            target_date="20260416",
            playback_command="cyber_recorder play -r 1",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            issue_path = save_issue_draft(
                work_dir,
                issue_draft,
                issue_timestamp="20260416_120000",
            )
            self.assertEqual(
                issue_path,
                work_dir / "issues" / "issue_20260416_120000.md",
            )
            self.assertTrue(issue_path.exists())

    def test_save_issue_draft_normalizes_human_readable_timestamp(self) -> None:
        issue_draft = IssueDraft(
            tag_text="demo_tag",
            vehicle="XZB600013",
            target_date="20260416",
            playback_command="cyber_recorder play -r 1",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            issue_path = save_issue_draft(
                work_dir,
                issue_draft,
                issue_timestamp="2026-04-16 12:00:00",
            )
            self.assertEqual(
                issue_path,
                work_dir / "issues" / "issue_20260416_120000.md",
            )
            self.assertTrue(issue_path.exists())

    def test_load_version_text_reads_file_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            version_path = Path(tmpdir) / "version.txt"
            version_path.write_text("demo-version", encoding="utf-8")

            version_text = load_version_text(version_path)

        self.assertEqual(version_text, "demo-version")

    def test_format_issue_data_path_truncates_prefix_before_date_and_vehicle(self) -> None:
        path_text = (
            "/media/road_test/20260415/XZB600007/01.20260415_101203/"
            "soc2/20260415101058.record.00001.101159.split"
        )

        issue_path_text = format_issue_data_path(
            path_text,
            "20260415",
            "XZB600007",
            "/media/nas/00.raw",
        )

        self.assertEqual(
            issue_path_text,
            "/media/nas/00.raw/20260415/XZB600007/01.20260415_101203/"
            "soc2/20260415101058.record.00001.101159.split",
        )

    def test_issue_draft_uses_explicit_default_issue_description(self) -> None:
        issue_draft = IssueDraft(
            tag_text="demo_tag",
            vehicle="XZB600013",
            target_date="20260416",
            playback_command="cyber_recorder play -r 1",
        )

        self.assertEqual(issue_draft.issue_description, DEFAULT_ISSUE_DESCRIPTION)


if __name__ == "__main__":
    unittest.main()
