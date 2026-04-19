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
    ReplayRecord,
    TagInfo,
    TaskEntry,
)
from utils import parser

from interface import replay_workflow


class TaskEntryTests(unittest.TestCase):
    def test_from_manifest_parts_groups_soc_paths(self) -> None:
        task_entry = TaskEntry.from_manifest_parts(
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
        task_entry = TaskEntry.from_manifest_parts(
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
        task_entry = TaskEntry.from_manifest_parts(
            time="2026-04-15 12:00:00",
            name="demo_tag",
            paths=[],
        )

        tag_info = TagInfo.from_task_entry(task_entry, before=15, after=5)

        self.assertEqual(tag_info.name, "demo_tag")
        self.assertEqual(tag_info.abs_start, "2026-04-15T11:59:45")
        self.assertEqual(tag_info.abs_end, "2026-04-15T12:00:05")

    def test_record_meta_roundtrip(self) -> None:
        task_entry = TaskEntry.from_manifest_parts(
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
        task_entry = TaskEntry.from_manifest_parts(
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

    def test_library_entry_cache_roundtrip(self) -> None:
        library_entry = LibraryEntry(
            tag="demo_tag",
            time="2026-04-15 12:00:00",
            vehicle="XZB600013",
            date="20260415",
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

    def test_parse_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "tasks.list"
            manifest_path.write_text(
                "\n".join(
                    [
                        "2026-04-15 12:00:01|tag_b|/data/soc2/b.record",
                        "2026-04-15 12:00:00|tag_a|/data/soc1/a.record",
                    ]
                ),
                encoding="utf-8",
            )

            task_entries = parser.parse_manifest(manifest_path)

        self.assertEqual([task.name for task in task_entries], ["tag_a", "tag_b"])
        self.assertEqual(task_entries[0].id, "01")
        self.assertEqual(task_entries[0].soc_paths["soc1"], ["/data/soc1/a.record"])


class ReplayWorkflowTests(unittest.TestCase):
    def test_build_source_replay_records_uses_tag_window(self) -> None:
        task_entry = TaskEntry.from_manifest_parts(
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
