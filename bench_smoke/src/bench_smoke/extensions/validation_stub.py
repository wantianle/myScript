"""
Reserved seam for algorithm validation of generated mcap files.

MVP does **not** execute automated validation; this module returns a SKIPPED
result so that the orchestrator can call through the seam without runtime
failures.

Future implementation flow (Phase N):
  1. Accept a :class:`~bench_smoke.models.RunContext` that records the
     paths of all generated ``.mcap`` files.
  2. For each ``.mcap``, run the project's algorithm validation pipeline
     (e.g. replay against perception / planning modules and compare against
     golden outputs).
  3. Collect per-mcap metrics and produce a machine-readable validation report.
  4. Return SUCCESS if all checks pass within configured thresholds, or
     FAILED with structured error details.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bench_smoke.models import RunContext, StepResult, ToolConfig


def validate_results(context: RunContext, config: ToolConfig) -> StepResult:
    """Placeholder for future algorithm validation of a complete run.

    Called by the orchestrator after metadata collection.  In the MVP this is a
    no-op stub that signals SKIPPED.

    Args:
        context: The active :class:`RunContext` containing
            ``generated_mcaps``.
        config: The active :class:`ToolConfig`.

    Returns:
        A :class:`StepResult` with status ``SKIPPED``.
    """
    from datetime import datetime, timezone

    from bench_smoke.models import StepResult, StepStatus

    now = datetime.now(timezone.utc).isoformat()
    return StepResult(
        name="validate_results",
        status=StepStatus.SKIPPED,
        started_at=now,
        ended_at=now,
        duration_sec=0.0,
        message="Algorithm validation is not implemented in the MVP",
    )


def run_algorithm_check(mcap_path: str) -> StepResult:
    """Placeholder for validating a single ``.mcap`` against golden outputs.

    Args:
        mcap_path: Absolute path to a single generated ``.mcap`` file.

    Returns:
        A :class:`StepResult` with status ``SKIPPED``.  The future
        implementation would return SUCCESS/FAILED with per-mcap metrics.
    """
    from datetime import datetime, timezone

    from bench_smoke.models import StepResult, StepStatus

    now = datetime.now(timezone.utc).isoformat()
    return StepResult(
        name="run_algorithm_check",
        status=StepStatus.SKIPPED,
        started_at=now,
        ended_at=now,
        duration_sec=0.0,
        message=f"Algorithm check for {mcap_path} is not implemented in the MVP",
    )
