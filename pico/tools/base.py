"""Shared tool primitives: ToolResult, ToolSpec, and helper functions.

These primitives are the foundation shared by both the generic tool registry
(pico.tools.generic) and the LabFlow tool registry (pico.tools.registry).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..config import DEFAULT_TOOL_OUTPUT_LIMIT, IGNORED_DIRS
from ..tool_context import ToolContext
from ..workspace import clip


@dataclass
class ToolResult:
    ok: bool
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    affected_paths: list[str] = field(default_factory=list)
    workspace_changed: bool = False

    def to_observation(self, limit: int = DEFAULT_TOOL_OUTPUT_LIMIT) -> str:
        status = "ok" if self.ok else f"error:{self.error_code or 'tool_error'}"
        return f"[{status}]\n" + clip(self.text, limit)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "text": self.text,
            "metadata": self.metadata,
            "error_code": self.error_code,
            "affected_paths": self.affected_paths,
            "workspace_changed": self.workspace_changed,
        }


@dataclass
class ToolSpec:
    name: str
    description: str
    schema: dict[str, Any]
    risky: bool
    runner: Callable[[ToolContext, dict[str, Any]], ToolResult]


def validate_tool_args(schema: dict[str, Any], args: dict[str, Any]) -> str | None:
    required = schema.get("required", [])
    for key in required:
        if key not in args:
            return f"missing required argument: {key}"
    properties = schema.get("properties", {})
    for key, value in args.items():
        spec = properties.get(key)
        if spec is None:
            return f"unexpected argument: {key}"
        expected = spec.get("type")
        if expected == "string" and not isinstance(value, str):
            return f"argument {key} must be a string"
        if expected == "integer" and not isinstance(value, int):
            return f"argument {key} must be an integer"
        if expected == "boolean" and not isinstance(value, bool):
            return f"argument {key} must be a boolean"
    return None


def relpath(ctx: ToolContext, path: Path) -> str:
    try:
        return path.relative_to(ctx.root).as_posix()
    except ValueError:
        return str(path)


def tool_signature(registry: dict[str, ToolSpec]) -> str:
    data = {name: {"schema": spec.schema, "risky": spec.risky} for name, spec in sorted(registry.items())}
    return json.dumps(data, sort_keys=True)


def shell_command_signature(name: str, args: dict[str, Any]) -> str:
    return json.dumps({"name": name, "args": args}, sort_keys=True, ensure_ascii=False)


def workspace_snapshot(root: Path) -> dict[str, tuple[int, int]]:
    snapshot: dict[str, tuple[int, int]] = {}
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for file_name in files:
            path = Path(current) / file_name
            try:
                rel = path.relative_to(root).as_posix()
                stat = path.stat()
            except OSError:
                continue
            snapshot[rel] = (int(stat.st_mtime_ns), int(stat.st_size))
    return snapshot
