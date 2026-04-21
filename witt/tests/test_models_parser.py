import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from core.models import (
    ChannelInfo,
    LibraryEntry,
    LogicConfig,
    RecordInfo,
    RecordMeta,
    ReplayHistoryEntry,
    ReplayRecord,
    TagInfo,
    TaskEntry,
    build_history_selection_label,
)
from utils import parser

from interface import workflow_replay as replay_workflow


class TaskEntryTests(unittest.TestCase):
    def test_from_record_paths_groups_soc_paths(self) -> None:
        task_entry = TaskEntry.from_record_paths(
            time="2026-04-15 12:00:00",
            name="demo_tag",
            paths=[
                "/data/soc1/foo.record",
                "/data/soc2/bar.record",
                "/data/other/baz.record",
            ],
        )

        self.assertEqual(task_entry.soc_paths["soc1"], ["/data/soc1/foo.record"])
        self.assertEqual(task_entry.soc_paths["soc2"], ["/data/soc2/bar.record"])
        self.assertEqual(len(task_entry.paths), 3)

    def test_assign_id_formats_two_digits(self) -> None:
        task_entry = TaskEntry.from_record_paths(
            time="2026-04-15 12:00:00",
            name="demo_tag",
            paths=[],
        )

        task_entry.assign_id(7)

        self.assertEqual(task_entry.id, "07")


class LogicConfigTests(unittest.TestCase):
    def test_from_dict_normalizes_blacklist_and_version(self) -> None:
        logic_config = LogicConfig.from_dict(
            {
                "vehicle": "XZB600013",
                "target_date": "20260415",
                "mode": "1",
                "version": Path("/tmp/version.txt"),
                "soc": "soc",
                "before": "15",
                "after": 5,
                "blacklist": "foo",
            }
        )

        self.assertEqual(logic_config.mode, 1)
        self.assertEqual(logic_config.before, 15)
        self.assertEqual(logic_config.after, 5)
        self.assertEqual(logic_config.blacklist, ["foo"])
        self.assertEqual(logic_config.version, Path("/tmp/version.txt"))


class MetadataModelTests(unittest.TestCase):
    def test_tag_info_from_task_entry_builds_expected_window(self) -> None:
        task_entry = TaskEntry.from_record_paths(
            time="2026-04-15 12:00:00",
            name="demo_tag",
            paths=[],
        )

        tag_info = TagInfo.from_task_entry(task_entry, before=15, after=5)

        self.assertEqual(tag_info.name, "demo_tag")
        self.assertEqual(tag_info.abs_start, "2026-04-15T11:59:45")
        self.assertEqual(tag_info.abs_end, "2026-04-15T12:00:05")

    def test_record_meta_roundtrip(self) -> None:
        task_entry = TaskEntry.from_record_paths(
            time="2026-04-15 12:00:00",
            name="demo_tag",
            paths=[],
        )
        record_meta = RecordMeta.from_task_entry(
            task_entry=task_entry,
            vehicle="XZB600013",
            date="20260415",
            before=15,
            after=5,
        )
        record_meta.update_soc_files(
            soc_name="soc1",
            file_names=["a.record", "b.record"],
            updated_at="2026-04-15 12:01:00",
        )

        restored_meta = RecordMeta.from_dict(record_meta.to_dict())

        self.assertEqual(restored_meta.tag_info.name, "demo_tag")
        self.assertEqual(restored_meta.files["soc1"], ["a.record", "b.record"])
        self.assertEqual(restored_meta.last_update["soc1"], "2026-04-15 12:01:00")

    def test_library_entry_from_record_meta(self) -> None:
        task_entry = TaskEntry.from_record_paths(
            time="2026-04-15 12:00:00",
            name="demo_tag",
            paths=[],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            tag_dir = Path(tmpdir) / "tag_dir"
            soc_dir = tag_dir / "soc1"
            soc_dir.mkdir(parents=True, exist_ok=True)
            record_file = soc_dir / "a.record"
            record_file.write_text("record", encoding="utf-8")

            record_meta = RecordMeta.from_task_entry(
                task_entry=task_entry,
                vehicle="XZB600013",
                date="20260415",
                before=15,
                after=5,
            )
            record_meta.update_soc_files(
                soc_name="soc1",
                file_names=[record_file.name],
                updated_at="2026-04-15 12:01:00",
            )

            library_entry = LibraryEntry.from_record_meta(record_meta, tag_dir)

        self.assertEqual(library_entry.tag, "demo_tag")
        self.assertEqual(library_entry.socs["soc1"][0].path, str(record_file.absolute()))
        self.assertEqual(library_entry.last_update["soc1"], "2026-04-15 12:01:00")

    def test_record_meta_build_soc_replay_records_skips_missing_files(self) -> None:
        task_entry = TaskEntry.from_record_paths(
            time="2026-04-15 12:00:00",
            name="demo_tag",
            paths=[],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            tag_dir = Path(tmpdir) / "tag_dir"
            soc_dir = tag_dir / "soc1"
            soc_dir.mkdir(parents=True, exist_ok=True)
            record_file = soc_dir / "a.record"
            record_file.write_text("record", encoding="utf-8")

            record_meta = RecordMeta.from_task_entry(
                task_entry=task_entry,
                vehicle="XZB600013",
                date="20260415",
                before=15,
                after=5,
            )
            record_meta.update_soc_files(
                soc_name="soc1",
                file_names=["missing.record", "a.record"],
                updated_at="2026-04-15 12:01:00",
            )

            replay_records = record_meta.build_soc_replay_records(tag_dir, "soc1")

        self.assertEqual(len(replay_records), 1)
        self.assertEqual(replay_records[0].path, str(record_file.absolute()))
        self.assertEqual(replay_records[0].duration, 20)

    def test_library_entry_cache_roundtrip(self) -> None:
        library_entry = LibraryEntry(
            tag="demo_tag",
            time="2026-04-15 12:00:00",
            socs={
                "soc1": [
                    ReplayRecord(
                        path="/tmp/a.record",
                        begin="2026-04-15T11:59:45",
                        duration=20,
                    )
                ]
            },
            last_update={"soc1": "2026-04-15 12:01:00"},
        )

        restored_entry = LibraryEntry.from_cache_dict(library_entry.to_cache_dict())

        self.assertEqual(restored_entry.tag, library_entry.tag)
        self.assertEqual(restored_entry.socs["soc1"][0].path, "/tmp/a.record")
        self.assertEqual(restored_entry.last_update["soc1"], "2026-04-15 12:01:00")

    def test_record_info_from_components_sorts_channels(self) -> None:
        record_info = RecordInfo.from_components(
            begin=datetime(2026, 4, 15, 12, 0, 0),
            end=datetime(2026, 4, 15, 12, 0, 10),
            duration=10.9,
            channels=[
                ChannelInfo(name="/b", count=2),
                ChannelInfo(name="/a", count=1),
            ],
        )

        self.assertEqual(record_info.duration, 10)
        self.assertEqual(
            [channel.name for channel in record_info.channels],
            ["/a", "/b"],
        )


class ParserTests(unittest.TestCase):
    def test_parse_range_logic(self) -> None:
        self.assertEqual(parser.parse_range_logic("5-10"), (5, 10))
        self.assertEqual(parser.parse_range_logic("7"), (7, 0))
        self.assertEqual(parser.parse_range_logic(""), (0, 0))

    def test_str_to_time_supports_iso_t_separator(self) -> None:
        parsed_time = parser.str_to_time("2026-04-15T10:16:08")

        self.assertEqual(parsed_time, datetime(2026, 4, 15, 10, 16, 8))

    def test_str_to_time_raises_explicit_error_for_invalid_format(self) -> None:
        with self.assertRaises(ValueError) as raised:
            parser.str_to_time("invalid-time")

        self.assertEqual(str(raised.exception), "无法识别的时间格式: invalid-time")

    def test_replay_history_entry_resolved_selection_label_uses_legacy_value_first(self) -> None:
        history_entry = ReplayHistoryEntry(
            created_at="2026-04-19 12:00:00",
            source_type="auto",
            replay_mode="standard",
            selection_label="legacy label",
            display_tag="demo_tag",
            issue_timestamp="2026-04-19 11:59:00",
            vehicle="XZB600001",
            target_date="20260419",
            records=[],
        )

        self.assertEqual(history_entry.resolved_selection_label, "legacy label")

    def test_replay_history_entry_to_dict_omits_redundant_selection_label(self) -> None:
        history_entry = ReplayHistoryEntry(
            created_at="2026-04-19 12:00:00",
            source_type="manual",
            replay_mode="standard",
            display_tag="manual",
            issue_timestamp="2026-04-19 11:59:00",
            vehicle="XZB600001",
            target_date="20260419",
            records=[
                ReplayRecord(
                    path="/tmp/demo.record",
                    begin="2026-04-19 12:00:00",
                    duration=10,
                )
            ],
        )

        raw_entry = history_entry.to_dict()

        self.assertNotIn("selection_label", raw_entry)
        self.assertEqual(
            history_entry.resolved_selection_label,
            build_history_selection_label(
                history_entry.records,
                history_entry.display_tag,
                history_entry.source_type,
            ),
        )

class ReplayWorkflowTests(unittest.TestCase):
    def test_build_source_replay_records_uses_tag_window(self) -> None:
        task_entry = TaskEntry.from_record_paths(
            time="2026-04-15 12:00:00",
            name="demo_tag",
            paths=[
                "/data/soc1/20260415120000.record.00002.120002",
                "/data/soc1/20260415120000.record.00001.120001",
            ],
        )
        raw_session = SimpleNamespace(
            ctx=SimpleNamespace(
                logic=SimpleNamespace(before=15, after=5)
            )
        )
        session = cast(Any, raw_session)

        replay_records = replay_workflow._build_source_replay_records(session, task_entry)

        self.assertEqual(len(replay_records), 2)
        self.assertEqual(
            [Path(record.path).name for record in replay_records],
            [
                "20260415120000.record.00001.120001",
                "20260415120000.record.00002.120002",
            ],
        )
        self.assertEqual(replay_records[0].begin, datetime(2026, 4, 15, 11, 59, 45))
        self.assertEqual(replay_records[0].duration, 20)


if __name__ == "__main__":
    unittest.main()
