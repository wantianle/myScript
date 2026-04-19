from typing import List, Optional


class WittCoreError(Exception):
    """Core-layer base exception for structured error propagation."""


class PathMappingError(WittCoreError):
    """Raised when a host path cannot be mapped into the execution environment."""


class CommandExecutionError(WittCoreError):
    """Raised when a command fails in docker/ssh execution."""


class ScriptExecutionError(WittCoreError):
    """Raised when a managed shell script fails with structured output."""

    def __init__(
        self,
        script_name: str,
        summary: str,
        details: Optional[List[str]] = None,
    ) -> None:
        super().__init__(summary)
        self.script_name = script_name
        self.summary = summary
        self.details = list(details or [])


class RecordInfoError(WittCoreError):
    """Raised when record metadata cannot be read or parsed."""


class RecordSplitError(WittCoreError):
    """Raised when record splitting fails."""


class TaskBatchPlanningError(WittCoreError):
    """Raised when a downloader batch cannot be planned."""


class VersionFileMissingError(TaskBatchPlanningError):
    """Raised when a task batch cannot proceed because version files are missing."""


class FindRecordError(WittCoreError):
    """Raised when record discovery cannot produce query candidates."""


class TagFileMissingError(FindRecordError):
    """Raised when a query root has candidate records but no tag files."""


class RuntimeEnvironmentError(WittCoreError):
    """Raised when runtime environment sync cannot be completed."""


class ReplayStackError(WittCoreError):
    """Raised when replay stack startup cannot be completed."""
