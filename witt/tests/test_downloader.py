import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock, patch

from core.engine.downloader import DownloadBatch, DownloadSummary, RecordDownloader
from core.errors import RecordSplitError
from core.models import TaskEntry


def _build_task_entry() -> TaskEntry:
    return TaskEntry(
        time="2026-04-19 12:00:00",
        name="demo_tag",
        soc_paths={"soc1": ["/tmp/source/soc1/demo.record"], "soc2": []},
        paths=["/tmp/source/soc1/demo.record"],
        id="01",
    )


def _build_downloader(
    mode: int = 1,
    recorder=None,
    executor=None,
    metadata_repository=None,
) -> RecordDownloader:
    raw_session = SimpleNamespace(
        ctx=SimpleNamespace(
            logic=SimpleNamespace(
                before=1,
                after=1,
                blacklist=[],
                mode=mode,
            ),
            vehicle="XZB600001",
            target_date="20260419",
        ),
        recorder=recorder or SimpleNamespace(split=Mock()),
        executor=executor or SimpleNamespace(fetch_file=Mock(), remove=Mock()),
    )
    return RecordDownloader(
        cast(Any, raw_session),
        cast(
            Any,
            metadata_repository
            or SimpleNamespace(load=Mock(side_effect=FileNotFoundError()), save=Mock()),
        ),
    )


class RecordDownloaderTests(unittest.TestCase):
    def test_sync_file_returns_slice_failure_reason(self) -> None:
        task_entry = _build_task_entry()
        downloader = _build_downloader(
            recorder=SimpleNamespace(
                split=Mock(side_effect=RecordSplitError("split failed"))
            )
        )

        failure_reason = downloader._sync_file(
            "/tmp/source/soc1/demo.record",
            "/tmp/output/demo.record.split",
            task_entry,
        )

        self.assertEqual(
            failure_reason,
            "切片失败: /tmp/source/soc1/demo.record，已清理当前批次",
        )

    def test_sync_file_returns_remote_fetch_failure_reason(self) -> None:
        task_entry = _build_task_entry()
        executor = SimpleNamespace(
            fetch_file=Mock(side_effect=RuntimeError("fetch failed")),
            remove=Mock(),
        )
        downloader = _build_downloader(
            mode=3,
            recorder=SimpleNamespace(split=Mock()),
            executor=executor,
        )

        failure_reason = downloader._sync_file(
            "/tmp/source/soc1/demo.record",
            "/tmp/output/demo.record.split",
            task_entry,
        )

        self.assertEqual(
            failure_reason,
            "远端拉取失败: /tmp/source/soc1/demo.record，已清理当前批次",
        )

    def test_post_process_task_returns_version_sync_failure_reason(self) -> None:
        task_entry = _build_task_entry()
        downloader = _build_downloader()
        file_infos = [
            (
                "/tmp/source/soc1/demo.record",
                "/tmp/output/soc1/demo.record.split",
                "soc1",
            )
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            save_dir = Path(tmpdir) / "01.20260419_120000" / "soc1"
            save_dir.mkdir(parents=True, exist_ok=True)

            with patch.object(
                downloader,
                "_sync_version_files",
                side_effect=OSError("copy failed"),
            ):
                failure_reason = downloader._post_process_task(
                    task_entry,
                    save_dir,
                    file_infos,
                )

        self.assertEqual(
            failure_reason,
            "version 同步失败: /tmp/source/soc1，已清理当前批次",
        )

    def test_post_process_task_returns_metadata_write_failure_reason(self) -> None:
        task_entry = _build_task_entry()
        metadata_repository = SimpleNamespace(
            load=Mock(side_effect=FileNotFoundError()),
            save=Mock(side_effect=OSError("write failed")),
        )
        downloader = _build_downloader(metadata_repository=metadata_repository)
        file_infos = [
            (
                "/tmp/source/soc1/demo.record",
                "/tmp/output/soc1/demo.record.split",
                "soc1",
            )
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            save_dir = Path(tmpdir) / "01.20260419_120000" / "soc1"
            save_dir.mkdir(parents=True, exist_ok=True)

            with patch.object(
                downloader,
                "_sync_version_files",
                return_value=[],
            ):
                failure_reason = downloader._post_process_task(
                    task_entry,
                    save_dir,
                    file_infos,
                )

            expected_meta_path = save_dir.parent / "meta.json"

        self.assertEqual(
            failure_reason,
            "metadata 写入失败: {0}，已清理当前批次".format(expected_meta_path),
        )

    def test_finalize_batch_preserves_specific_failure_reason(self) -> None:
        task_entry = _build_task_entry()
        downloader = _build_downloader()
        summary = DownloadSummary()

        with tempfile.TemporaryDirectory() as tmpdir:
            save_dir = Path(tmpdir) / "01.20260419_120000" / "soc1"
            batch = DownloadBatch(
                task=task_entry,
                soc_name="soc1",
                save_dir=save_dir,
                items=[],
            )

            with patch.object(downloader, "_cleanup_failed_batch") as cleanup_failed_batch:
                downloader._finalize_batch(
                    batch,
                    [],
                    "切片失败: /tmp/source/soc1/demo.record，已清理当前批次",
                    summary,
                )

        cleanup_failed_batch.assert_called_once_with(save_dir)
        self.assertEqual(len(summary.failed_batches), 1)
        self.assertEqual(
            summary.failed_batches[0].reason,
            "切片失败: /tmp/source/soc1/demo.record，已清理当前批次",
        )


if __name__ == "__main__":
    unittest.main()
