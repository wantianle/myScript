from typing import List, Optional


class PathMappingError(Exception):
    """Raised when a host path cannot be mapped into the execution environment."""


class CommandExecutionError(Exception):
    """Raised when a command fails in docker/ssh execution."""


class ScriptExecutionError(Exception):
    """Raised when a managed runtime operation fails with structured output."""

    def __init__(
        self,
        operation_name: str,
        summary: str,
        details: Optional[List[str]] = None,
    ) -> None:
        super().__init__(summary)
        self.operation_name = operation_name
        self.summary = summary
        self.details = list(details or [])


class RecordInfoError(Exception):
    """Raised when record metadata cannot be read or parsed."""


class RecordSplitError(Exception):
    """Raised when record splitting fails."""


class TaskBatchPlanningError(Exception):
    """Raised when a downloader batch cannot be planned."""


class FindRecordError(Exception):
    """Raised when record discovery cannot produce query candidates."""


class RuntimeEnvironmentError(Exception):
    """Raised when runtime environment sync cannot be completed."""


class ReplayStackError(Exception):
    """Raised when replay stack startup cannot be completed."""
