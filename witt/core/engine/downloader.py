import logging
import shutil
from dataclasses import dataclass, field
from alive_progress import alive_bar
from datetime import datetime, timedelta
from pathlib import Path
from shlex import quote
from typing import List

from core.errors import RecordSplitError, TaskBatchPlanningError, VersionFileMissingError
from core.models import RecordMeta, TaskEntry
from utils import parser


@dataclass
class DownloadItem:
    src: Path
    dest: Path


@dataclass
class DownloadBatch:
    task: TaskEntry
    soc_name: str
    save_dir: Path
    items: List[DownloadItem]


@dataclass
class SkippedBatch:
    task_name: str
    soc_name: str
    reason: str


@dataclass
class FailedBatch:
    task_name: str
    soc_name: str
    reason: str


@dataclass
class CompletedBatch:
    task_name: str
    soc_name: str
    save_dir: Path
    file_count: int


@dataclass
class DownloadSummary:
    total_files: int = 0
    completed_batches: List[CompletedBatch] = field(default_factory=list)
    skipped_batches: List[SkippedBatch] = field(default_factory=list)
    failed_batches: List[FailedBatch] = field(default_factory=list)


class RecordDownloader:
    def __init__(self, session, metadata_repository):
        self.session = session
        self.ctx = session.ctx
        self.recorder = session.recorder
        self.metadata_repository = metadata_repository

    @property
    def mode(self):
        return self.ctx.logic.mode

    def _prepare_dir(self, target_dir: Path):
        """
        彻底清理目标目录，确保没有旧数据干扰
        """
        if target_dir.exists():
            shutil.rmtree(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

    def _cleanup_failed_batch(self, save_dir: Path):
        """清理失败批次的残留数据，避免留下半成品目录"""
        if save_dir.exists():
            shutil.rmtree(save_dir)
        tag_dir = save_dir.parent
        if tag_dir.exists() and not any(tag_dir.iterdir()):
            tag_dir.rmdir()

    def _get_version_files(self, src_dir: Path):
        if self.mode == 3:
            find_cmd = (
                f"find {quote(str(src_dir))} -maxdepth 1 -type f "
                f"-name 'version*' 2>/dev/null"
            )
            result_str = self.session.executor.execute(find_cmd).strip()
            return [line.strip() for line in result_str.splitlines() if line.strip()]
        return sorted(src_dir.glob("version*"))

    def _ensure_version_files(self, src_dir: Path):
        version_files = self._get_version_files(src_dir)
        if not version_files:
            raise VersionFileMissingError(f"{src_dir} 未找到 version 文件，已跳过当前任务")
        return version_files

    def _sync_version_files(self, src_dir: Path, save_dir: Path):
        version_files = self._ensure_version_files(src_dir)
        synced_files = []
        if self.mode == 3:
            for remote_v_path in version_files:
                v_name = Path(remote_v_path).name
                v_dest = save_dir / v_name
                self.session.executor.fetch_file(remote_v_path, v_dest)
                synced_files.append(v_dest)
                logging.info(f"[SYNC_VERSION] 成功同步远程文件: {v_name}")
        else:
            for v_src in version_files:
                v_dest = save_dir / v_src.name
                shutil.copy2(v_src, v_dest)
                synced_files.append(v_dest)
        return synced_files

    def _save_contract(self, task_entry: TaskEntry, save_dir, file_infos):
        """保存元数据，实现数据信息缓存，减少底层重复计算，并为回播提供必要的上下文信息"""
        tag_dir = save_dir.parent
        meta_path = tag_dir / "meta.json"
        record_meta = RecordMeta.from_task_entry(
            task_entry=task_entry,
            vehicle=self.ctx.vehicle,
            date=self.ctx.target_date,
            before=int(self.ctx.logic.before),
            after=int(self.ctx.logic.after),
        )
        if meta_path.exists():
            try:
                existing_meta = self.metadata_repository.load(meta_path)
                record_meta.merge_existing(existing_meta)
            except Exception:
                logging.warning("元数据文件损坏，执行全量重写")
        current_soc = file_infos[0][2]
        record_meta.update_soc_files(
            soc_name=current_soc,
            file_names=[Path(file_info[1]).name for file_info in file_infos],
            updated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        self.metadata_repository.save(meta_path, record_meta)

    def _post_process_task(self, task_entry: TaskEntry, save_dir, file_infos):
        """生成元数据、README 和 version"""
        # 同步 version
        src_dir = Path(file_infos[0][0]).parent
        version_files = self._sync_version_files(src_dir, save_dir)
        # 生成元数据文件
        self._save_contract(task_entry, save_dir, file_infos)

        # 生成 README
        v_content = version_files[0].read_text(encoding="utf-8", errors="replace")
        nas_path = save_dir.relative_to(Path(self.ctx.host.dest_root))
        before = int(self.ctx.logic.before)
        after = int(self.ctx.logic.after)
        play_lead = 10
        duration = max(before + after, 0)
        target_start = before - play_lead
        play_start = target_start if 0 <= target_start < duration else 0
        records_str = " ".join([Path(f[1]).name for f in file_infos])
        readme_content = f"""- **tag：** {task_entry.time} {task_entry.name} duration: {before + after}s
- **问题描述：**
> 填写补充描述
- **预期结果：**
> 填写正确情况
- **车辆软硬件信息：**
```json
{v_content}
```
- **数据路径：**
```bash
cd {self.ctx.host.nas_root}/{nas_path}
```
- **数据时刻：**
```bash
cyber_recorder play -s {play_start} -f {records_str}
```
"""
        readme_path = save_dir / "README.md"
        readme_path.write_text(readme_content, encoding="utf-8")
        logging.info(f"[TASK_COMPLETE] Tag: {task_entry.name} | Saved to: {save_dir}")
        logging.info(f"  Files: {[Path(f[1]).name for f in file_infos]}")

    def _sync_file(self, src, dest, task_entry: TaskEntry) -> bool:
        """生成 .split 文件，全量覆盖，最后清理中间文件"""
        logic = self.ctx.logic
        tag_dt = parser.str_to_time(task_entry.time)
        t_start = tag_dt - timedelta(seconds=int(logic.before))
        t_end = tag_dt + timedelta(seconds=int(logic.after))
        blacklist = logic.blacklist
        if blacklist:
            logging.info(f"[RECORDER_COMPRESS] Blacklist: {','.join(blacklist)}")
        if self.ctx.logic.mode != 3:
            try:
                self.session.recorder.split(src, dest, t_start, t_end, blacklist)
                return True
            except RecordSplitError:
                if Path(dest).exists():
                    Path(dest).unlink()
                return False
        remote_out = f"{src}.split"
        try:
            self.session.executor.remove(remote_out)
        except Exception:
            pass
        try:
            self.session.recorder.split(src, remote_out, t_start, t_end, blacklist)
        except RecordSplitError:
            try:
                self.session.executor.remove(remote_out)
            except Exception:
                pass
            return False
        try:
            self.session.executor.fetch_file(remote_out, dest)
            return True
        except Exception as e:
            logging.debug(f"{src} 拉取异常: {e}")
            if Path(dest).exists():
                Path(dest).unlink()
            return False
        finally:
            try:
                self.session.executor.remove(remote_out)
            except Exception:
                pass

    def _plan_task_batch(self, task_entry: TaskEntry, soc_name, paths):
        src_dir = Path(paths[0]).parent
        self._ensure_version_files(src_dir)
        save_dir = self.ctx.get_task_dir(task_entry.id, task_entry.time, soc_name)
        self._prepare_dir(save_dir)
        return DownloadBatch(
            task=task_entry,
            soc_name=soc_name,
            save_dir=save_dir,
            items=[
                DownloadItem(
                    src=Path(p),
                    dest=save_dir / (Path(p).name + ".split"),
                )
                for p in paths
            ],
        )

    def _collect_task_batches(self, task_list):
        batches = []
        skipped_batches = []
        for task_entry in task_list:
            for soc_name, paths in task_entry.soc_paths.items():
                if not paths:
                    continue
                try:
                    batch = self._plan_task_batch(task_entry, soc_name, paths)
                    batches.append(batch)
                except TaskBatchPlanningError as e:
                    skipped_batches.append(
                        SkippedBatch(
                            task_name=task_entry.name,
                            soc_name=soc_name,
                            reason=str(e),
                        )
                    )
                    logging.warning(
                        f"[TASK_SKIP] Tag: {task_entry.name} | Soc: {soc_name} | {e}"
                    )
        return batches, skipped_batches

    def plan_download(self, task_list) -> DownloadSummary:
        batches, skipped_batches = self._collect_task_batches(task_list)
        return DownloadSummary(
            total_files=sum(len(batch.items) for batch in batches),
            skipped_batches=skipped_batches,
        )

    def _finalize_batch(self, batch, processed_files, batch_failed, summary: DownloadSummary):
        task_entry = batch.task
        if batch_failed or not processed_files:
            self._cleanup_failed_batch(batch.save_dir)
            summary.failed_batches.append(
                FailedBatch(
                    task_name=task_entry.name,
                    soc_name=batch.soc_name,
                    reason="批次存在异常，已清理残留数据",
                )
            )
            logging.warning(
                f"[TASK_SKIP] Tag: {task_entry.name} | Soc: {batch.soc_name} | 批次存在异常，已清理残留数据"
            )
            return
        try:
            self._post_process_task(task_entry, batch.save_dir, processed_files)
            summary.completed_batches.append(
                CompletedBatch(
                    task_name=task_entry.name,
                    soc_name=batch.soc_name,
                    save_dir=batch.save_dir,
                    file_count=len(processed_files),
                )
            )
        except Exception as e:
            self._cleanup_failed_batch(batch.save_dir)
            summary.failed_batches.append(
                FailedBatch(
                    task_name=task_entry.name,
                    soc_name=batch.soc_name,
                    reason=f"{batch.save_dir} 后处理失败，已清理当前批次",
                )
            )
            logging.warning(
                f"[TASK_POST_PROCESS_FAIL] Tag: {task_entry.name} | Soc: {batch.soc_name} | {e}"
            )

    def _run_task_batch(self, batch, bar, summary: DownloadSummary):
        task_entry = batch.task
        processed_files = []
        batch_failed = False
        for item in batch.items:
            bar.text = f"-> [Tag: {task_entry.name[:15]}]"
            if not batch_failed:
                if self._sync_file(item.src, item.dest, task_entry):
                    processed_files.append(
                        (str(item.src), str(item.dest), batch.soc_name)
                    )
                else:
                    batch_failed = True
            bar()
        self._finalize_batch(batch, processed_files, batch_failed, summary)

    def download_records(self, task_list) -> DownloadSummary:
        """
        负责高层调度和进度条
        """
        batches, skipped_batches = self._collect_task_batches(task_list)
        summary = DownloadSummary(skipped_batches=skipped_batches)
        if not batches:
            return summary
        total_files = sum(len(batch.items) for batch in batches)
        summary.total_files = total_files
        with alive_bar(
            total_files,
            title="Progress",
            theme="classic",
            stats=False,
            elapsed=False,
        ) as bar:
            for batch in batches:
                self._run_task_batch(batch, bar, summary)
        return summary
