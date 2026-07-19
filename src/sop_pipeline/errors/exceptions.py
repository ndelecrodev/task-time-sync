"""Custom exceptions for recurring business errors in the pipeline.

Every exception raised on purpose by this project inherits from
:class:`SopPipelineError`, so a caller can catch the whole family with a single
``except`` clause while still being able to react to a specific failure.
"""


class SopPipelineError(Exception):
    """Base class for every error raised on purpose by the pipeline."""


class TaskValidationError(SopPipelineError):
    """Raised when a Jira issue cannot be converted into a valid ``Task``."""


class ExcelWriteError(SopPipelineError):
    """Raised when the spreadsheet cannot be opened, updated or saved."""


class NotificationError(SopPipelineError):
    """Raised when a deadline alert cannot be delivered to a Teams webhook."""


class StorageError(SopPipelineError):
    """Raised when the spreadsheet cannot be downloaded from or uploaded to B2."""
