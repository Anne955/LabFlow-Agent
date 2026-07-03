from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .errors import SafetyViolationError, ToolExecutionError
from .tool_context import ToolContext
from .tools import ToolResult, ToolSpec, shell_command_signature, validate_tool_args

ApprovalCallback = Callable[[ToolSpec, dict[str, Any]], bool]


@dataclass
class ToolExecutor:
    registry: dict[str, ToolSpec]
    context: ToolContext
    approval: str = "ask"
    read_only: bool = False
    approval_callback: ApprovalCallback | None = None
    last_signature: str | None = None
    allowed_tools: set[str] | None = None
    events: list[dict[str, Any]] = field(default_factory=list)

    def execute(self, name: str, args: dict[str, Any]) -> ToolResult:
        if self.allowed_tools is not None and name not in self.allowed_tools:
            return ToolResult(False, f"tool is not allowed: {name}", error_code="tool_not_allowed")
        spec = self.registry.get(name)
        if spec is None:
            return ToolResult(False, f"unknown tool: {name}", error_code="unknown_tool")
        validation_error = validate_tool_args(spec.schema, args)
        if validation_error:
            return ToolResult(False, validation_error, error_code="invalid_args")
        signature = shell_command_signature(name, args)
        if signature == self.last_signature:
            return ToolResult(
                False,
                "repeated identical tool call; choose a different tool or return a final answer",
                error_code="repeated_tool_call",
            )
        if spec.risky:
            approval_error = self._approval_error(spec, args)
            if approval_error:
                return approval_error
        self.last_signature = signature
        try:
            return spec.runner(self.context, args)
        except SafetyViolationError:
            raise
        except ToolExecutionError as exc:
            return ToolResult(False, str(exc), error_code=exc.error_code)
        except ValueError as exc:
            return ToolResult(False, str(exc), error_code="path_escape")
        except Exception as exc:  # noqa: BLE001 - tool boundary isolates unexpected failures
            self.events.append({"level": "warning", "name": name, "error": f"unexpected: {exc!r}"})
            return ToolResult(False, f"tool failed: {exc}", error_code="tool_exception")

    def _approval_error(self, spec: ToolSpec, args: dict[str, Any]) -> ToolResult | None:
        if self.read_only:
            return ToolResult(False, f"risky tool blocked in read-only mode: {spec.name}", error_code="read_only")
        if self.approval == "never":
            return ToolResult(False, f"risky tool blocked by approval policy: {spec.name}", error_code="approval_denied")
        if self.approval == "auto":
            return None
        approved = self.approval_callback(spec, args) if self.approval_callback else False
        if not approved:
            return ToolResult(False, f"risky tool not approved: {spec.name}", error_code="approval_denied")
        return None
