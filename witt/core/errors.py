class WittCoreError(Exception):
    """Core-layer base exception for structured error propagation."""


class PathMappingError(WittCoreError):
    """Raised when a host path cannot be mapped into the execution environment."""


class CommandExecutionError(WittCoreError):
    """Raised when a command fails in docker/ssh execution."""


class RecordInfoError(WittCoreError):
    """Raised when record metadata cannot be read or parsed."""


class RecordSplitError(WittCoreError):
    """Raised when record splitting fails."""


class TaskBatchPlanningError(WittCoreError):
    """Raised when a downloader batch cannot be planned."""


class VersionFileMissingError(TaskBatchPlanningError):
    """Raised when a task batch cannot proceed because version files are missing."""
