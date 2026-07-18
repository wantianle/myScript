"""
Extension stubs for future capabilities.

These modules reserve seams for HTML report generation, NAS auto-upload,
and algorithm validation — all explicitly out of scope for the MVP.  Each stub
returns a SKIPPED :class:`StepResult` so that callers (including the
orchestrator) can reference the extension points without runtime errors.

Every extension is designed to consume stable output artifacts produced by the
MVP flow (``RunSummary`` JSON, ``RunContext`` state, generated ``.mcap`` files)
and does **not** participate in the one-click or debug paths today.
"""

from bench_smoke.extensions.report_stub import generate_report, render_html_report
from bench_smoke.extensions.upload_stub import upload_to_nas, verify_upload
from bench_smoke.extensions.validation_stub import validate_results, run_algorithm_check

__all__ = [
    "generate_report",
    "render_html_report",
    "upload_to_nas",
    "verify_upload",
    "validate_results",
    "run_algorithm_check",
]
