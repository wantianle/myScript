import tempfile
import unittest
from pathlib import Path

from core.models import LibraryEntry, RecordMeta, ReplayRecord, TaskEntry
from core.repository import LibraryCacheRepository, MetadataRepository


class LibraryCacheRepositoryTests(unittest.TestCase):
    def test_save_and_load_library_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "local_library.json"
            repository = LibraryCacheRepository(cache_path)
            library_entries = [
                LibraryEntry(
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
            ]

            repository.save("fp-1", library_entries)
            loaded_entries = repository.load("fp-1")

        self.assertIsNotNone(loaded_entries)
        assert loaded_entries is not None
        self.assertEqual(loaded_entries[0].tag, "demo_tag")
        self.assertEqual(loaded_entries[0].socs["soc1"][0].path, "/tmp/a.record")

    def test_load_returns_none_when_fingerprint_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "local_library.json"
            repository = LibraryCacheRepository(cache_path)
            repository.save("fp-1", [])

            loaded_entries = repository.load("fp-2")

        self.assertIsNone(loaded_entries)


class MetadataRepositoryTests(unittest.TestCase):
    def test_save_and_load_record_meta(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            meta_path = Path(tmpdir) / "meta.json"
            repository = MetadataRepository()
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
                file_names=["a.record"],
                updated_at="2026-04-15 12:01:00",
            )

            repository.save(meta_path, record_meta)
            loaded_meta = repository.load(meta_path)

        self.assertEqual(loaded_meta.tag_info.name, "demo_tag")
        self.assertEqual(loaded_meta.files["soc1"], ["a.record"])
        self.assertEqual(loaded_meta.last_update["soc1"], "2026-04-15 12:01:00")

    def test_iter_record_meta_scans_nested_meta_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            repository = MetadataRepository()
            task_entry = TaskEntry.from_manifest_parts(
                time="2026-04-15 12:00:00",
                name="demo_tag",
                paths=[],
            )
            first_meta_path = root_dir / "a" / "meta.json"
            second_meta_path = root_dir / "b" / "c" / "meta.json"
            first_meta_path.parent.mkdir(parents=True, exist_ok=True)
            second_meta_path.parent.mkdir(parents=True, exist_ok=True)

            first_meta = RecordMeta.from_task_entry(
                task_entry=task_entry,
                vehicle="XZB600013",
                date="20260415",
                before=15,
                after=5,
            )
            second_meta = RecordMeta.from_task_entry(
                task_entry=task_entry,
                vehicle="XZT500001",
                date="20260415",
                before=10,
                after=0,
            )
            repository.save(first_meta_path, first_meta)
            repository.save(second_meta_path, second_meta)

            scanned = list(repository.iter_record_meta(root_dir))

        self.assertEqual(len(scanned), 2)
        scanned_dirs = sorted(str(tag_dir.relative_to(root_dir)) for tag_dir, _ in scanned)
        self.assertEqual(scanned_dirs, ["a", "b/c"])


if __name__ == "__main__":
    unittest.main()
