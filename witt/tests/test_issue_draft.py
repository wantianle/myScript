import tempfile
import unittest
from pathlib import Path

from core.issue_draft import (
    IssueDraft,
    build_issue_filename,
    load_version_text,
    render_issue_markdown,
    save_issue_draft,
)


class IssueDraftTests(unittest.TestCase):
    def test_build_issue_filename_defaults_to_timestamp(self) -> None:
        self.assertEqual(
            build_issue_filename("20260416_120000"),
            "issue_20260416_120000.md",
        )

    def test_render_issue_markdown_includes_replay_fields(self) -> None:
        issue_draft = IssueDraft(
            tag_text="demo_tag",
            replay_mode="standard",
            replay_status="正常结束",
            vehicle="XZB600013",
            target_date="20260416",
            playback_command="cyber_recorder play -r 2",
            data_path_text="/tmp/data",
            version_text='{"version":"demo"}',
            playback_rate=2.0,
            playback_range_text="5s-10s",
            playback_channels=["/apollo/foo"],
            record_paths=["/tmp/data/a.record"],
        )

        markdown_text = render_issue_markdown(issue_draft)

        self.assertIn("demo_tag", markdown_text)
        self.assertIn("standard", markdown_text)
        self.assertIn("正常结束", markdown_text)
        self.assertIn("cyber_recorder play -r 2", markdown_text)
        self.assertIn("rate: x2", markdown_text)
        self.assertIn("channels: /apollo/foo", markdown_text)

    def test_save_issue_draft_writes_into_work_dir_issues(self) -> None:
        issue_draft = IssueDraft(
            tag_text="demo_tag",
            replay_mode="standard",
            replay_status="正常结束",
            vehicle="XZB600013",
            target_date="20260416",
            playback_command="cyber_recorder play -r 1",
            data_path_text="/tmp/data",
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

    def test_load_version_text_reads_file_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            version_path = Path(tmpdir) / "version.txt"
            version_path.write_text("demo-version", encoding="utf-8")

            version_text = load_version_text(version_path)

        self.assertEqual(version_text, "demo-version")


if __name__ == "__main__":
    unittest.main()
