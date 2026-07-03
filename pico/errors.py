from __future__ import annotations


class PicoError(Exception):
    """Base class for all typed Pico errors."""


class SafetyViolationError(PicoError):
    """Raised when an action would breach a safety boundary (e.g. writing raw data).

    Must propagate to the caller; never silently converted to a ToolResult.
    """


class ToolExecutionError(PicoError):
    """Raised by a tool for a known, recoverable business error.

    The ToolExecutor converts this into a ToolResult(success=False, error_code=...).
    """

    def __init__(self, message: str, error_code: str = "tool_error") -> None:
        super().__init__(message)
        self.error_code = error_code
