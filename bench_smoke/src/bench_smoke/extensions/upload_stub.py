"""
Reserved seam for automatic NAS upload of run artifacts.

MVP does **not** upload results to NAS; this module returns a SKIPPED result
so that the orchestrator can call through the seam without runtime failures.

Future implementation flow (Phase N):
  1. Accept a :class:`~bench_smoke.models.RunContext` that tracks the
     local run directory and generated ``.mcap`` file paths.
  2. Compute the NAS target path (e.g. under ``/media/nas/smoke_results/``).
  3. Use ``rsync`` or a comparable copy strategy to push the entire run
     directory (JSON summaries, logs, mcap files).
  4. Optionally verify checksums / file counts post-upload.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bench_smoke.models import RunContext, StepResult, ToolConfig


def upload_to_nas(context: RunContext, config: ToolConfig) -> StepResult:
    """Placeholder for future NAS auto-upload.

    Called by the orchestrator after a successful run.  In the MVP this is a
    no-op stub that signals SKIPPED.

    Args:
        context: The active :class:`RunContext` containing local paths.
        config: The active :class:`ToolConfig` (includes ``nas_root``).

    Returns:
        A :class:`StepResult` with status ``SKIPPED``.
    """
    from datetime import datetime, timezone

    from bench_smoke.models import StepResult, StepStatus

    now = datetime.now(timezone.utc).isoformat()
    return StepResult(
        name="upload_to_nas",
        status=StepStatus.SKIPPED,
        started_at=now,
        ended_at=now,
        duration_sec=0.0,
        message="NAS auto-upload is not implemented in the MVP",
    )


def verify_upload(context: RunContext) -> bool:
    """Placeholder for post-upload verification.

    Args:
        context: The :class:`RunContext` that was uploaded.

    Returns:
        ``False`` in the MVP.  The future implementation would return ``True``
        when the NAS-side artifacts match the local run directory.
    """
    return False
