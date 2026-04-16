import importlib
import logging
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any, cast


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

from core.models import HostConfig, LogicConfig, TaskEntry
from core.repository import MetadataRepository
from core.errors import RecordSplitError


def _get_record_downloader_class():
    """延迟导入下载器，避免测试桩后的模块级晚导入。"""
    downloader_module = importlib.import_module("core.engine.downloader")
    return downloader_module.RecordDownloader


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
    def __init__(
        self,
        root_dir: Path,
        mode: int = 1,
        recorder=None,
        executor=None,
    ) -> None:
        self.ctx = _FakeContext(root_dir)
        self.ctx.logic.mode = mode
        self.recorder = recorder
        self.executor = executor


class _FakeExecutor:
    def __init__(self) -> None:
        self.remove_calls = []
        self.fetch_calls = []
        self.remove_side_effects = []
        self.fetch_error = None
        self.write_partial_file = False

    def remove(self, path_text: str) -> None:
        self.remove_calls.append(path_text)
        if self.remove_side_effects:
            remove_error = self.remove_side_effects.pop(0)
            if remove_error is not None:
                raise remove_error

    def fetch_file(self, remote_path: str, local_dest: Path) -> None:
        self.fetch_calls.append((remote_path, local_dest))
        if self.write_partial_file:
            local_dest.write_text("partial", encoding="utf-8")
        if self.fetch_error is not None:
            raise self.fetch_error


class _FakeRecorder:
    def __init__(self, split_error=None) -> None:
        self.split_calls = []
        self.split_error = split_error

    def split(self, src, dest, start_dt, end_dt, blacklist) -> None:
        self.split_calls.append((src, dest, start_dt, end_dt, list(blacklist or [])))
        if self.split_error is not None:
            raise self.split_error


class DownloaderPlanningTests(unittest.TestCase):
    def test_plan_download_counts_files_when_version_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_path = Path(tmpdir)
            source_dir = root_path / "source" / "soc1"
            source_dir.mkdir(parents=True, exist_ok=True)
            (source_dir / "version.txt").write_text("demo", encoding="utf-8")
            record_path = source_dir / "demo.record"
            record_path.write_text("record", encoding="utf-8")

            downloader = _get_record_downloader_class()(
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

            downloader = _get_record_downloader_class()(
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

    def test_post_process_task_keeps_version_and_meta_without_generating_readme(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_path = Path(tmpdir)
            source_dir = root_path / "source" / "soc1"
            source_dir.mkdir(parents=True, exist_ok=True)
            version_path = source_dir / "version.txt"
            version_path.write_text("demo-version", encoding="utf-8")
            record_path = source_dir / "demo.record"
            record_path.write_text("record", encoding="utf-8")
            save_dir = root_path / "dest" / "01.20260415_120000" / "soc1"
            save_dir.mkdir(parents=True, exist_ok=True)
            split_path = save_dir / "demo.record.split"
            split_path.write_text("split", encoding="utf-8")

            downloader = _get_record_downloader_class()(
                cast(Any, _FakeSession(root_path)),
                metadata_repository=MetadataRepository(),
            )
            task_entry = TaskEntry.from_manifest_parts(
                time="2026-04-15 12:00:00",
                name="demo_tag",
                paths=[str(record_path)],
            )

            downloader._post_process_task(
                task_entry,
                save_dir,
                [(str(record_path), str(split_path), "soc1")],
            )

            self.assertTrue((save_dir / "version.txt").exists())
            self.assertTrue((save_dir.parent / "meta.json").exists())
            self.assertFalse((save_dir / "README.md").exists())


class DownloaderSyncFileTests(unittest.TestCase):
    def test_sync_file_logs_remote_cleanup_failures_when_split_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_path = Path(tmpdir)
            executor = _FakeExecutor()
            executor.remove_side_effects = [
                RuntimeError("cleanup before split failed"),
                RuntimeError("cleanup after split failed"),
            ]
            recorder = _FakeRecorder(split_error=RecordSplitError("split failed"))
            downloader = _get_record_downloader_class()(
                cast(
                    Any,
                    _FakeSession(
                        root_path,
                        mode=3,
                        recorder=recorder,
                        executor=executor,
                    ),
                ),
                metadata_repository=MetadataRepository(),
            )
            task_entry = TaskEntry.from_manifest_parts(
                time="2026-04-15 12:00:00",
                name="demo_tag",
                paths=["/remote/soc1/demo.record"],
            )
            dest_path = root_path / "demo.record.split"

            with self.assertLogs(level=logging.DEBUG) as captured_logs:
                sync_result = downloader._sync_file(
                    "/remote/soc1/demo.record",
                    dest_path,
                    task_entry,
                )

        self.assertFalse(sync_result)
        self.assertEqual(
            executor.remove_calls,
            [
                "/remote/soc1/demo.record.split",
                "/remote/soc1/demo.record.split",
            ],
        )
        self.assertEqual(len(recorder.split_calls), 1)
        self.assertEqual(recorder.split_calls[0][1], "/remote/soc1/demo.record.split")
        self.assertIn("REMOTE_SPLIT_CLEANUP_FAIL", "\n".join(captured_logs.output))

    def test_sync_file_removes_partial_local_file_when_remote_fetch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_path = Path(tmpdir)
            executor = _FakeExecutor()
            executor.remove_side_effects = [
                None,
                RuntimeError("cleanup after fetch failed"),
            ]
            executor.fetch_error = RuntimeError("scp failed")
            executor.write_partial_file = True
            recorder = _FakeRecorder()
            downloader = _get_record_downloader_class()(
                cast(
                    Any,
                    _FakeSession(
                        root_path,
                        mode=3,
                        recorder=recorder,
                        executor=executor,
                    ),
                ),
                metadata_repository=MetadataRepository(),
            )
            task_entry = TaskEntry.from_manifest_parts(
                time="2026-04-15 12:00:00",
                name="demo_tag",
                paths=["/remote/soc1/demo.record"],
            )
            dest_path = root_path / "demo.record.split"

            with self.assertLogs(level=logging.DEBUG) as captured_logs:
                sync_result = downloader._sync_file(
                    "/remote/soc1/demo.record",
                    dest_path,
                    task_entry,
                )

        self.assertFalse(sync_result)
        self.assertFalse(dest_path.exists())
        self.assertEqual(
            executor.fetch_calls,
            [("/remote/soc1/demo.record.split", dest_path)],
        )
        self.assertEqual(
            executor.remove_calls,
            [
                "/remote/soc1/demo.record.split",
                "/remote/soc1/demo.record.split",
            ],
        )
        captured_text = "\n".join(captured_logs.output)
        self.assertIn("拉取异常", captured_text)
        self.assertIn("REMOTE_SPLIT_CLEANUP_FAIL", captured_text)


if __name__ == "__main__":
    unittest.main()
