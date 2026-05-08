import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock, patch

from core.engine.downloader import (
    DownloadBatch,
    DownloadItem,
    DownloadSummary,
    FailedBatch,
    RecordDownloader,
)
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
    source_executor=None,
    metadata_repository=None,
) -> RecordDownloader:
    raw_session = SimpleNamespace(
        ctx=SimpleNamespace(
            logic=SimpleNamespace(
                before=1,
                after=1,
                blacklist=[],
                mode=mode,
                vehicle="XZB600001",
                target_date="20260419",
            ),
            get_task_dir=Mock(return_value=Path("/tmp/output")),
        ),
        recorder=recorder or SimpleNamespace(split=Mock()),
        source_executor=source_executor
        or SimpleNamespace(fetch_file=Mock(), remove=Mock(), execute=Mock()),
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
            "Tag: demo_tag | 切片失败: /tmp/source/soc1/demo.record，已清理当前 Tag",
        )

    def test_sync_file_returns_remote_fetch_failure_reason(self) -> None:
        task_entry = _build_task_entry()
        source_executor = SimpleNamespace(
            fetch_file=Mock(side_effect=RuntimeError("fetch failed")),
            remove=Mock(),
        )
        downloader = _build_downloader(
            mode=3,
            recorder=SimpleNamespace(split=Mock()),
            source_executor=source_executor,
        )

        failure_reason = downloader._sync_file(
            "/tmp/source/soc1/demo.record",
            "/tmp/output/demo.record.split",
            task_entry,
        )

        self.assertEqual(
            failure_reason,
            "Tag: demo_tag | 远端拉取失败: /tmp/source/soc1/demo.record，已清理当前 Tag",
        )

    def test_post_process_task_returns_version_sync_failure_reason(self) -> None:
        task_entry = _build_task_entry()
        downloader = _build_downloader()

        with tempfile.TemporaryDirectory() as tmpdir:
            save_dir = Path(tmpdir) / "01.20260419_120000" / "soc1"
            save_dir.mkdir(parents=True, exist_ok=True)
            batch = DownloadBatch(
                task=task_entry,
                soc_name="soc1",
                save_dir=save_dir,
                items=[],
            )
            processed_items = [
                DownloadItem(
                    src=Path("/tmp/source/soc1/demo.record"),
                    dest=Path("/tmp/output/soc1/demo.record.split"),
                )
            ]

            with patch.object(
                downloader,
                "_sync_version_files",
                side_effect=OSError("copy failed"),
            ):
                failure_reason = downloader._post_process_task(
                    batch,
                    processed_items,
                )

        self.assertEqual(
            failure_reason,
            "Tag: demo_tag | version 同步失败: /tmp/source/soc1，已清理当前 Tag",
        )

    def test_post_process_task_returns_metadata_write_failure_reason(self) -> None:
        task_entry = _build_task_entry()
        metadata_repository = SimpleNamespace(
            load=Mock(side_effect=FileNotFoundError()),
            save=Mock(side_effect=OSError("write failed")),
        )
        downloader = _build_downloader(metadata_repository=metadata_repository)

        with tempfile.TemporaryDirectory() as tmpdir:
            save_dir = Path(tmpdir) / "01.20260419_120000" / "soc1"
            save_dir.mkdir(parents=True, exist_ok=True)
            batch = DownloadBatch(
                task=task_entry,
                soc_name="soc1",
                save_dir=save_dir,
                items=[],
            )
            processed_items = [
                DownloadItem(
                    src=Path("/tmp/source/soc1/demo.record"),
                    dest=Path("/tmp/output/soc1/demo.record.split"),
                )
            ]

            with patch.object(
                downloader,
                "_sync_version_files",
                return_value=[],
            ):
                failure_reason = downloader._post_process_task(
                    batch,
                    processed_items,
                )

            expected_meta_path = save_dir.parent / "meta.json"

        self.assertEqual(
            failure_reason,
            "Tag: demo_tag | metadata 写入失败: {0}，已清理当前 Tag".format(
                expected_meta_path
            ),
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
                    "Tag: demo_tag | 切片失败: /tmp/source/soc1/demo.record，已清理当前 Tag",
                    summary,
                )

        cleanup_failed_batch.assert_called_once_with(batch)
        self.assertEqual(len(summary.failed_batches), 1)
        self.assertEqual(
            summary.failed_batches[0].reason,
            "Tag: demo_tag | 切片失败: /tmp/source/soc1/demo.record，已清理当前 Tag",
        )
        self.assertEqual(summary.failed_batches[0].task_id, "01")
        self.assertEqual(summary.failed_batches[0].task_time, "2026-04-19 12:00:00")

    def test_cleanup_failed_batch_removes_only_failed_tag_dir(self) -> None:
        task_entry = _build_task_entry()
        downloader = _build_downloader()

        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            failed_tag_dir = root_dir / "01.20260419_120000"
            failed_soc_dir = failed_tag_dir / "soc2"
            other_tag_dir = root_dir / "02.20260419_120005"
            failed_soc_dir.mkdir(parents=True)
            other_tag_dir.mkdir()
            (failed_soc_dir / "bad.record.split").write_text("", encoding="utf-8")
            (other_tag_dir / "good.record.split").write_text("", encoding="utf-8")
            batch = DownloadBatch(
                task=task_entry,
                soc_name="soc2",
                save_dir=failed_soc_dir,
                items=[],
            )

            downloader._cleanup_failed_batch(batch)

            self.assertFalse(failed_tag_dir.exists())
            self.assertTrue(other_tag_dir.exists())

    def test_run_task_batch_skips_remaining_soc_after_tag_failure(self) -> None:
        task_entry = _build_task_entry()
        task_entry.soc_paths["soc2"] = ["/tmp/source/soc2/demo.record"]
        downloader = _build_downloader()
        summary = DownloadSummary(
            failed_batches=[
                FailedBatch(
                    task_name="demo_tag",
                    soc_name="soc1",
                    reason="failed",
                    task_id="01",
                    task_time="2026-04-19 12:00:00",
                )
            ]
        )
        batch = DownloadBatch(
            task=task_entry,
            soc_name="soc2",
            save_dir=Path("/tmp/output/soc2"),
            items=[
                DownloadItem(
                    src=Path("/tmp/source/soc2/demo.record"),
                    dest=Path("/tmp/output/soc2/demo.record.split"),
                )
            ],
        )
        bar = Mock()

        with patch.object(downloader, "_prepare_dir") as prepare_dir:
            downloader._run_task_batch(batch, bar, summary)

        prepare_dir.assert_not_called()
        downloader.session.recorder.split.assert_not_called()
        bar.assert_called_once_with()

    def test_plan_download_does_not_prepare_output_dir(self) -> None:
        task_entry = _build_task_entry()
        downloader = _build_downloader()

        with patch.object(
            downloader,
            "_ensure_version_files",
            return_value=[Path("/tmp/version.txt")],
        ):
            with patch.object(downloader, "_prepare_dir") as prepare_dir:
                summary = downloader.plan_download([task_entry])

        prepare_dir.assert_not_called()
        self.assertEqual(summary.total_files, 1)


if __name__ == "__main__":
    unittest.main()
