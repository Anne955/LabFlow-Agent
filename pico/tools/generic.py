"""Generic pico-harness tools and the generic tool registry.

These are the safety-test-bed tools (list_files, read_file, search, run_shell,
write_file, patch_file, delegate) exercised by tests/test_tools_safety.py. They
are intentionally separate from the LabFlow registry in pico.tools.registry,
which is what the LabFlow runtime actually exposes (safety-by-default: no
arbitrary shell/file-write tools).
"""
from __future__ import annotations

import re
import subprocess
from typing import Any

from ..config import DEFAULT_TOOL_OUTPUT_LIMIT, IGNORED_DIRS
from ..tool_context import ToolContext
from ..workspace import clip, file_freshness, iter_workspace_files
from .base import ToolResult, ToolSpec, relpath


def tool_list_files(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    path = ctx.path_resolver(str(args.get("path", ".")))
    max_entries = int(args.get("max_entries", 200))
    if not path.exists():
        return ToolResult(False, f"path does not exist: {path}", error_code="not_found")
    if path.is_file():
        return ToolResult(True, relpath(ctx, path), metadata={"entries": 1})
    entries = []
    try:
        for child in sorted(path.iterdir(), key=lambda item: item.name.lower()):
            if child.name in IGNORED_DIRS:
                continue
            suffix = "/" if child.is_dir() else ""
            entries.append(relpath(ctx, child) + suffix)
            if len(entries) >= max_entries:
                break
    except OSError as exc:
        return ToolResult(False, str(exc), error_code="io_error")
    return ToolResult(True, "\n".join(entries), metadata={"entries": len(entries)})


def tool_read_file(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    path = ctx.path_resolver(str(args["path"]))
    start_line = max(1, int(args.get("start_line", 1)))
    max_lines = max(1, int(args.get("max_lines", 200)))
    if not path.is_file():
        return ToolResult(False, f"not a file: {relpath(ctx, path)}", error_code="not_file")
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return ToolResult(False, str(exc), error_code="io_error")
    start_index = start_line - 1
    selected = lines[start_index : start_index + max_lines]
    numbered = [f"{idx}\t{line}" for idx, line in enumerate(selected, start=start_line)]
    if start_index + max_lines < len(lines):
        numbered.append("... [truncated]")
    metadata = {"path": relpath(ctx, path), "freshness": file_freshness(path), "lines": len(lines)}
    return ToolResult(True, "\n".join(numbered), metadata=metadata)


def tool_search(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    pattern = str(args["pattern"])
    start = ctx.path_resolver(str(args.get("path", ".")))
    glob_pattern = args.get("glob")
    max_matches = max(1, int(args.get("max_matches", 100)))
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        return ToolResult(False, f"invalid regex: {exc}", error_code="invalid_regex")
    matches = []
    paths = [start] if start.is_file() else iter_workspace_files(ctx.root, start)
    for path in paths:
        if glob_pattern and not path.match(str(glob_pattern)):
            continue
        try:
            if path.stat().st_size > 1_000_000:
                continue
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for idx, line in enumerate(lines, start=1):
            if regex.search(line):
                matches.append(f"{relpath(ctx, path)}:{idx}: {line}")
                if len(matches) >= max_matches:
                    return ToolResult(True, "\n".join(matches), metadata={"matches": len(matches)})
    return ToolResult(True, "\n".join(matches), metadata={"matches": len(matches)})


def tool_run_shell(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    command = str(args["command"])
    timeout = min(max(1, int(args.get("timeout", 20))), 120)
    try:
        completed = subprocess.run(
            command,
            cwd=str(ctx.root),
            shell=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            env=ctx.shell_env_provider(),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return ToolResult(False, f"command timed out after {timeout}s", error_code="timeout", metadata={"command": command, "timeout": timeout, "stdout": exc.stdout, "stderr": exc.stderr})
    output = ""
    if completed.stdout:
        output += completed.stdout
    if completed.stderr:
        output += ("\n[stderr]\n" if output else "[stderr]\n") + completed.stderr
    if not output:
        output = f"command exited with {completed.returncode} and no output"
    return ToolResult(completed.returncode == 0, clip(output, DEFAULT_TOOL_OUTPUT_LIMIT), error_code=None if completed.returncode == 0 else "nonzero_exit", metadata={"command": command, "returncode": completed.returncode})


def tool_write_file(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    path = ctx.path_resolver(str(args["path"]))
    content = str(args.get("content", ""))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        return ToolResult(False, str(exc), error_code="io_error")
    relative = relpath(ctx, path)
    return ToolResult(True, f"wrote {len(content.encode('utf-8'))} bytes to {relative}", metadata={"path": relative, "freshness": file_freshness(path)}, affected_paths=[relative], workspace_changed=True)


def tool_patch_file(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    path = ctx.path_resolver(str(args["path"]))
    old_text = str(args["old_text"])
    new_text = str(args["new_text"])
    if not path.is_file():
        return ToolResult(False, f"not a file: {relpath(ctx, path)}", error_code="not_file")
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return ToolResult(False, str(exc), error_code="io_error")
    count = content.count(old_text)
    if count != 1:
        return ToolResult(False, f"old_text must appear exactly once; found {count}", error_code="ambiguous_patch")
    updated = content.replace(old_text, new_text, 1)
    try:
        path.write_text(updated, encoding="utf-8")
    except OSError as exc:
        return ToolResult(False, str(exc), error_code="io_error")
    relative = relpath(ctx, path)
    return ToolResult(True, f"patched {relative}", metadata={"path": relative, "freshness": file_freshness(path)}, affected_paths=[relative], workspace_changed=True)


def tool_delegate(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    if ctx.spawn_delegate is None:
        return ToolResult(False, "delegate is not available", error_code="unavailable")
    task = str(args["task"])
    max_steps = min(max(1, int(args.get("max_steps", 3))), 5)
    return ctx.spawn_delegate(task, max_steps)


LIST_FILES_SCHEMA = {"type": "object", "properties": {"path": {"type": "string"}, "max_entries": {"type": "integer"}}, "required": []}
READ_FILE_SCHEMA = {"type": "object", "properties": {"path": {"type": "string"}, "start_line": {"type": "integer"}, "max_lines": {"type": "integer"}}, "required": ["path"]}
SEARCH_SCHEMA = {"type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}, "glob": {"type": "string"}, "max_matches": {"type": "integer"}}, "required": ["pattern"]}
RUN_SHELL_SCHEMA = {"type": "object", "properties": {"command": {"type": "string"}, "timeout": {"type": "integer"}}, "required": ["command"]}
WRITE_FILE_SCHEMA = {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}
PATCH_FILE_SCHEMA = {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}
DELEGATE_SCHEMA = {"type": "object", "properties": {"task": {"type": "string"}, "max_steps": {"type": "integer"}}, "required": ["task"]}


def build_tool_registry(context: ToolContext) -> dict[str, ToolSpec]:
    registry = {
        "list_files": ToolSpec("list_files", "List files under a workspace path.", LIST_FILES_SCHEMA, False, tool_list_files),
        "read_file": ToolSpec("read_file", "Read a text file with line numbers.", READ_FILE_SCHEMA, False, tool_read_file),
        "search": ToolSpec("search", "Search text files with a regular expression.", SEARCH_SCHEMA, False, tool_search),
        "run_shell": ToolSpec("run_shell", "Run a shell command in the workspace.", RUN_SHELL_SCHEMA, True, tool_run_shell),
        "write_file": ToolSpec("write_file", "Create or overwrite a file.", WRITE_FILE_SCHEMA, True, tool_write_file),
        "patch_file": ToolSpec("patch_file", "Replace exactly one text occurrence in a file.", PATCH_FILE_SCHEMA, True, tool_patch_file),
    }
    if context.depth < context.max_depth and context.spawn_delegate is not None:
        registry["delegate"] = ToolSpec("delegate", "Delegate a read-only subtask to a child agent.", DELEGATE_SCHEMA, False, tool_delegate)
    return registry
