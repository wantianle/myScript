import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from core.errors import FindRecordError, TagFileMissingError
from core.engine import record_finder


class RecordFinderTests(unittest.TestCase):
    def test_parse_tag_message_supports_two_time_formats(self) -> None:
        direct_message = "demo_tag : 2026/4/19 12:00:00"
        am_pm_message = "demo_tag : 4/19/2026, 12:00:05 PM"

        direct_tag, direct_time = record_finder.parse_tag_message(direct_message)
        am_pm_tag, am_pm_time = record_finder.parse_tag_message(am_pm_message)

        self.assertEqual(direct_tag, "demo_tag")
        self.assertEqual(direct_time, datetime(2026, 4, 19, 12, 0, 0))
        self.assertEqual(am_pm_tag, "demo_tag")
        self.assertEqual(am_pm_time, datetime(2026, 4, 19, 12, 0, 5))

    def test_find_local_tasks_keeps_last_file_before_window_for_each_soc(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = Path(tmpdir)
            tag_file = data_root / "demo_tag_20260419.pb.txt"
            tag_file.write_text(
                'msg: "demo_tag : 2026/4/19 12:00:00"\n',
                encoding="utf-8",
            )

            record_paths = [
                data_root / "soc1" / "20260419.record.00000.115940",
                data_root / "soc1" / "20260419.record.00001.115950",
                data_root / "soc1" / "20260419.record.00002.120004",
                data_root / "soc1" / "20260419.record.00003.120005",
                data_root / "soc2" / "20260419.record.00000.115942",
                data_root / "soc2" / "20260419.record.00001.115944",
                data_root / "soc2" / "20260419.record.00002.120001",
            ]
            for record_path in record_paths:
                record_path.parent.mkdir(parents=True, exist_ok=True)
                record_path.write_text("record", encoding="utf-8")

            task_entries = record_finder.find_local_tasks(
                data_root,
                target_date="20260419",
                before=15,
                after=5,
            )

        self.assertEqual(len(task_entries), 1)
        self.assertEqual(task_entries[0].id, "01")
        self.assertEqual(
            task_entries[0].paths,
            [
                str(record_paths[0]),
                str(record_paths[5]),
                str(record_paths[1]),
                str(record_paths[6]),
                str(record_paths[2]),
            ],
        )

    def test_find_local_tasks_returns_empty_paths_when_tag_has_no_matching_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = Path(tmpdir)
            tag_file = data_root / "demo_tag_20260419.pb.txt"
            tag_file.write_text(
                'msg: "demo_tag : 2026/4/19 12:00:00"\n',
                encoding="utf-8",
            )

            task_entries = record_finder.find_local_tasks(
                data_root,
                target_date="20260419",
                before=15,
                after=5,
            )

        self.assertEqual(len(task_entries), 1)
        self.assertEqual(task_entries[0].paths, [])

    def test_find_local_tasks_sorts_tasks_and_assigns_stable_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = Path(tmpdir)
            tag_file = data_root / "demo_tag_20260419.pb.txt"
            tag_file.write_text(
                "\n".join(
                    [
                        'msg: "tag_b : 2026/4/19 12:00:01"',
                        'msg: "tag_a : 2026/4/19 12:00:00"',
                    ]
                ),
                encoding="utf-8",
            )
            record_path = data_root / "soc1" / "20260419.record.00000.120000"
            record_path.parent.mkdir(parents=True, exist_ok=True)
            record_path.write_text("record", encoding="utf-8")

            task_entries = record_finder.find_local_tasks(
                data_root,
                target_date="20260419",
                before=0,
                after=5,
            )

        self.assertEqual([task_entry.name for task_entry in task_entries], ["tag_a", "tag_b"])
        self.assertEqual([task_entry.id for task_entry in task_entries], ["01", "02"])

    def test_find_tasks_from_path_texts_supports_callback_based_loading(self) -> None:
        path_texts = [
            "/remote/root/soc1/20260419.record.00000.115950",
            "/remote/root/soc1/20260419.record.00001.120002",
            "/remote/root/soc2/20260419.record.00000.115952",
            "/remote/root/soc2/20260419.record.00001.120001",
            "/remote/root/demo_tag_20260419.pb.txt",
        ]
        tag_contents = {
            "/remote/root/demo_tag_20260419.pb.txt": 'msg: "demo_tag : 2026/4/19 12:00:00"\n'
        }

        task_entries = record_finder.find_tasks_from_path_texts(
            path_texts,
            lambda path_text: tag_contents[path_text],
            target_date="20260419",
            before=15,
            after=5,
        )

        self.assertEqual(len(task_entries), 1)
        self.assertEqual(
            task_entries[0].paths,
            [
                "/remote/root/soc1/20260419.record.00000.115950",
                "/remote/root/soc2/20260419.record.00000.115952",
                "/remote/root/soc2/20260419.record.00001.120001",
                "/remote/root/soc1/20260419.record.00001.120002",
            ],
        )

    def test_find_local_tasks_raises_when_tag_files_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = Path(tmpdir)
            record_path = data_root / "soc1" / "20260419.record.00000.120000"
            record_path.parent.mkdir(parents=True, exist_ok=True)
            record_path.write_text("record", encoding="utf-8")

            with self.assertRaises(TagFileMissingError):
                record_finder.find_local_tasks(
                    data_root,
                    target_date="20260419",
                    before=15,
                    after=5,
                )

    def test_find_local_tasks_raises_when_tag_has_no_valid_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = Path(tmpdir)
            tag_file = data_root / "demo_tag_20260419.pb.txt"
            tag_file.write_text("not-a-valid-tag-line\n", encoding="utf-8")

            with self.assertRaises(FindRecordError):
                record_finder.find_local_tasks(
                    data_root,
                    target_date="20260419",
                    before=15,
                    after=5,
                )

    def test_find_local_tasks_raises_when_data_root_has_no_related_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = Path(tmpdir)
            unrelated_file = data_root / "notes.txt"
            unrelated_file.write_text("demo", encoding="utf-8")

            with self.assertRaises(FindRecordError):
                record_finder.find_local_tasks(
                    data_root,
                    target_date="20260419",
                    before=15,
                    after=5,
                )

if __name__ == "__main__":
    unittest.main()
