"""
Reserved seam for HTML report generation.

MVP does **not** produce HTML; this module returns a SKIPPED result so that
the orchestrator can call through the seam without runtime failures.

Future implementation flow (Phase N):
  1. Accept a :class:`~bench_smoke.models.RunSummary` or its on-disk JSON
     (``summary.json``).
  2. Read :class:`~bench_smoke.models.StepResult` entries and artifacts.
  3. Render a self-contained HTML page suitable for bench-side consumption.
  4. Write output to ``<run_dir>/report.html`` and return SUCCESS.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from bench_smoke.models import RunSummary, StepResult, ToolConfig


def generate_report(summary: RunSummary, config: ToolConfig) -> StepResult:
    """Placeholder for future HTML report generation.

    Called by the orchestrator after ``summarize``.  In the MVP this is a
    no-op stub that signals SKIPPED.

    Args:
        summary: The final :class:`RunSummary` for a completed (or failed) run.
        config: The active :class:`ToolConfig`.

    Returns:
        A :class:`StepResult` with status ``SKIPPED``.
    """
    from datetime import datetime, timezone

    from bench_smoke.models import StepResult, StepStatus

    now = datetime.now(timezone.utc).isoformat()
    return StepResult(
        name="generate_report",
        status=StepStatus.SKIPPED,
        started_at=now,
        ended_at=now,
        duration_sec=0.0,
        message="HTML report generation is not implemented in the MVP",
    )


def render_html_report(summary_path: str) -> Optional[str]:
    """Placeholder for rendering a standalone HTML report from a summary file.

    Args:
        summary_path: Filesystem path to the ``summary.json`` written by
            :func:`bench_smoke.result_store.write_summary`.

    Returns:
        ``None`` in the MVP.  The future implementation would return the
        absolute path to the generated ``report.html``.
    """
    return None
