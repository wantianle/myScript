import tempfile
import unittest
from pathlib import Path
import sys
from contextlib import contextmanager
from types import ModuleType
from typing import Any, cast
from core.engine.downloader import RecordDownloader
from core.models import HostConfig, LogicConfig, TaskEntry
from core.repository import MetadataRepository

@contextmanager
def _fake_alive_bar(*args, **kwargs):
    class _DummyBar:
        text = ""

        def __call__(self):
            return None

    yield _DummyBar()


fake_alive_progress = ModuleType("alive_progress")
setattr(fake_alive_progress, "alive_bar", _fake_alive_bar)
sys.modules.setdefault("alive_progress", fake_alive_progress)


class _FakeContext:
    def __init__(self, root_dir: Path) -> None:
        self.host = HostConfig(
            mdrive_root=str(root_dir / "mdrive"),
            nas_root=str(root_dir / "nas"),
            data_root=str(root_dir / "data"),
            dest_root=str(root_dir / "dest"),
        )
        self.logic = LogicConfig(
            vehicle="XZB600013",
            target_date="20260415",
            mode=1,
            version="",
            soc="soc",
            before=15,
            after=5,
            blacklist=[],
        )

    @property
    def vehicle(self) -> str:
        return self.logic.vehicle

    @property
    def target_date(self) -> str:
        return self.logic.target_date

    def get_task_dir(self, task_id: str, task_time: str, soc: str = "") -> Path:
        folder_name = "{0}.{1}".format(task_id, task_time.replace(":", "").replace(" ", "_"))
        task_path = Path(self.host.dest_root) / folder_name
        if soc:
            task_path = task_path / soc
        return task_path


class _FakeSession:
    def __init__(self, root_dir: Path) -> None:
        self.ctx = _FakeContext(root_dir)
        self.recorder = None


class DownloaderPlanningTests(unittest.TestCase):
    def test_plan_download_counts_files_when_version_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_path = Path(tmpdir)
            source_dir = root_path / "source" / "soc1"
            source_dir.mkdir(parents=True, exist_ok=True)
            (source_dir / "version.txt").write_text("demo", encoding="utf-8")
            record_path = source_dir / "demo.record"
            record_path.write_text("record", encoding="utf-8")

            downloader = RecordDownloader(
                cast(Any, _FakeSession(root_path)),
                metadata_repository=MetadataRepository(),
            )
            task_entry = TaskEntry.from_manifest_parts(
                time="2026-04-15 12:00:00",
                name="demo_tag",
                paths=[str(record_path)],
            )
            task_entry.assign_id(1)

            summary = downloader.plan_download([task_entry])

        self.assertEqual(summary.total_files, 1)
        self.assertEqual(len(summary.skipped_batches), 0)

    def test_plan_download_skips_batch_when_version_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_path = Path(tmpdir)
            source_dir = root_path / "source" / "soc1"
            source_dir.mkdir(parents=True, exist_ok=True)
            record_path = source_dir / "demo.record"
            record_path.write_text("record", encoding="utf-8")

            downloader = RecordDownloader(
                cast(Any, _FakeSession(root_path)),
                metadata_repository=MetadataRepository(),
            )
            task_entry = TaskEntry.from_manifest_parts(
                time="2026-04-15 12:00:00",
                name="demo_tag",
                paths=[str(record_path)],
            )
            task_entry.assign_id(1)

            summary = downloader.plan_download([task_entry])

        self.assertEqual(summary.total_files, 0)
        self.assertEqual(len(summary.skipped_batches), 1)
        self.assertIn("未找到 version 文件", summary.skipped_batches[0].reason)


if __name__ == "__main__":
    unittest.main()
