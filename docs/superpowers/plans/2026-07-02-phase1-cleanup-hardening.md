# Phase 1: 清理与加固 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove redundant compatibility shims, programmatically enforce raw-data read-only protection, and refine tool-execution exception handling so safety violations are never silently swallowed.

**Architecture:** Introduce a small `pico/errors.py` hierarchy (`SafetyViolationError`, `ToolExecutionError`). Wire the existing-but-unused `assert_raw_data_readonly` into write paths and the tool executor. Make `ToolExecutor.execute` catch in three tiers (safety → tool-business → unexpected) instead of one broad `except Exception`. Convert LabFlow tool business errors to typed exceptions. Delete the two zero-reference shim modules and fix imports. Keep the generic tools in `tools.py` intact (they are the tested pico-harness safety bed, not dead code).

**Tech Stack:** Python 3.10+, standard library only, `unittest` test suite, `ruff` linter.

## Global Constraints

- Zero external runtime dependencies — `pyproject.toml` `dependencies = []` stays empty.
- Python `>=3.10` (uses `X | None` union syntax, `from __future__ import annotations`).
- `ruff check` must pass with rules `E,F,I,UP,B` at line-length 100.
- `pytest tests/` must stay fully green after every task.
- Safety violations must propagate (raise), never be converted to a silent `ToolResult(success=False)`.
- Existing public tool signatures (`tool_*` functions, `ToolSpec`, `ToolResult`) must not change shape — only add fields/methods.
- Language: code comments and docstrings may be English; user-facing report strings stay as-is.

## Spec Deviation (important)

The approved spec (§3.1) called for removing the generic tool implementations `tool_run_shell`, `tool_write_file`, `tool_patch_file` from `pico/tools.py` as "dead code." Code verification shows this is **incorrect**: `tests/test_tools_safety.py:12` imports `from pico.tools import build_tool_registry as build_legacy_tool_registry` and exercises `run_shell`, `write_file`, `patch_file` to test path-escape rejection, read-only blocking, approval policy, and shell-env sanitization. These are the generic pico-harness safety tests. Removing them would delete real coverage.

**Adjusted Task 5** keeps the generic tools and instead documents the dual-registry design. The shim-file removal (Task 6) is unaffected — verified zero references.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `pico/errors.py` | Create | Central typed exception hierarchy: `PicoError`, `SafetyViolationError`, `ToolExecutionError` (with `error_code`). |
| `pico/safety/__init__.py` | Modify | Re-export `SafetyViolationError` and existing guard functions. |
| `pico/safety/guard.py` | Modify | Make `assert_raw_data_readonly` raise `SafetyViolationError` instead of `ValueError`. |
| `pico/tool_executor.py` | Modify | Three-tier exception handling; call `assert_raw_data_readonly` before risky write tools. |
| `pico/labflow_tools.py` | Modify | Wrap write paths with `assert_raw_data_readonly`; raise `ToolExecutionError` for known business errors. |
| `pico/tools.py` | Modify | Add module docstring clarifying the generic-harness registry; no behavior change. |
| `pico/agent_loop.py` | Delete | Unused re-export shim. |
| `pico/session_store.py` | Delete | Unused re-export shim. |
| `tests/test_phase1_safety_enforcement.py` | Create | New tests for programmatic read-only enforcement and exception tiers. |
| `tests/test_labflow_guard.py` | Modify | Update any test expecting `ValueError` from raw-data writes to expect `SafetyViolationError`. |

---

## Task 1: Create the typed error hierarchy

**Files:**
- Create: `pico/errors.py`

**Interfaces:**
- Produces: `PicoError(Exception)`, `SafetyViolationError(PicoError)`, `ToolExecutionError(PicoError)` with attribute `error_code: str`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_phase1_errors.py`:

```python
from __future__ import annotations

import unittest

from pico.errors import PicoError, SafetyViolationError, ToolExecutionError


class ErrorHierarchyTests(unittest.TestCase):
    def test_safety_violation_is_pico_error(self):
        self.assertTrue(issubclass(SafetyViolationError, PicoError))

    def test_tool_execution_carries_error_code(self):
        err = ToolExecutionError("batch missing", error_code="not_found")
        self.assertEqual(err.error_code, "not_found")
        self.assertIn("batch missing", str(err))

    def test_tool_execution_is_pico_error(self):
        self.assertTrue(issubclass(ToolExecutionError, PicoError))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_phase1_errors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pico.errors'`

- [ ] **Step 3: Write minimal implementation**

Create `pico/errors.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_phase1_errors.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Lint and commit**

```bash
ruff check pico/errors.py tests/test_phase1_errors.py
git add pico/errors.py tests/test_phase1_errors.py
git commit -m "feat(errors): add PicoError, SafetyViolationError, ToolExecutionError"
```

---

## Task 2: Make `assert_raw_data_readonly` raise `SafetyViolationError`

**Files:**
- Modify: `pico/safety/guard.py:30-33`
- Modify: `pico/safety/__init__.py`

**Interfaces:**
- Consumes: `SafetyViolationError` from Task 1.
- Produces: `assert_raw_data_readonly(root, path)` now raises `SafetyViolationError`; re-exported from `pico.safety`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_phase1_rawdata_readonly.py`:

```python
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pico.errors import SafetyViolationError
from pico.safety.guard import assert_raw_data_readonly


class RawDataReadonlyTests(unittest.TestCase):
    def test_writing_batch_data_raises_safety_violation(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "data" / "batch_001" / "spectra" / "x.csv"
            raw.parent.mkdir(parents=True)
            with self.assertRaises(SafetyViolationError):
                assert_raw_data_readonly(root, raw)

    def test_writing_outputs_is_allowed(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            out = root / "outputs" / "batch_001" / "qc_summary.csv"
            out.parent.mkdir(parents=True)
            assert_raw_data_readonly(root, out)  # must not raise

    def test_writing_data_raw_raises(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "data" / "raw" / "sample.csv"
            raw.parent.mkdir(parents=True)
            with self.assertRaises(SafetyViolationError):
                assert_raw_data_readonly(root, raw)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_phase1_rawdata_readonly.py -v`
Expected: FAIL — raises `ValueError` (an `AssertionError` from `assertRaises(SafetyViolationError)` because `ValueError` is not a `SafetyViolationError`).

- [ ] **Step 3: Update `guard.py`**

In `pico/safety/guard.py`, replace the import block and the function body. Add the import at the top (after `from pathlib import Path`):

```python
from ..errors import SafetyViolationError
```

Replace `assert_raw_data_readonly` (lines 30-33) with:

```python
def assert_raw_data_readonly(root: Path, path: Path) -> None:
    rel = path.resolve().relative_to(root.resolve()).parts
    if len(rel) >= 2 and rel[0] == "data" and (rel[1] == "raw" or rel[1].startswith("batch_")):
        raise SafetyViolationError(f"raw data path is read-only: {path}")
```

- [ ] **Step 4: Re-export from the safety package**

Replace the entire contents of `pico/safety/__init__.py` with:

```python
from __future__ import annotations

from .guard import (
    assert_raw_data_readonly,
    resolve_output_path,
    resolve_preprocessed_path,
    resolve_registered_script,
    resolve_report_path,
    resolve_trace_path,
    resolve_workspace_path,
    sanitize_batch_id,
)

__all__ = [
    "assert_raw_data_readonly",
    "resolve_output_path",
    "resolve_preprocessed_path",
    "resolve_registered_script",
    "resolve_report_path",
    "resolve_trace_path",
    "resolve_workspace_path",
    "sanitize_batch_id",
]
```

- [ ] **Step 5: Run the new test plus existing guard tests**

Run: `python -m pytest tests/test_phase1_rawdata_readonly.py tests/test_labflow_guard.py -v`
Expected: PASS. If `tests/test_labflow_guard.py` has a case asserting `ValueError` from a raw-data write, update it to assert `SafetyViolationError` (see Task 7).

- [ ] **Step 6: Lint and commit**

```bash
ruff check pico/safety/
git add pico/safety/guard.py pico/safety/__init__.py tests/test_phase1_rawdata_readonly.py
git commit -m "feat(safety): assert_raw_data_readonly raises SafetyViolationError"
```

---

## Task 3: Wire read-only enforcement into LabFlow write paths

**Files:**
- Modify: `pico/labflow_tools.py` (imports + `tool_generate_report`, `tool_export_workflow_log`, `tool_run_preprocess_script` write points)

**Interfaces:**
- Consumes: `assert_raw_data_readonly` from Task 2.
- Produces: every LabFlow tool that writes a file calls `assert_raw_data_readonly` before writing.

- [ ] **Step 1: Write the failing test**

Create `tests/test_phase1_labflow_write_guard.py`:

```python
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pico.errors import SafetyViolationError
from pico.labflow_tools import tool_generate_report
from pico.security import safe_shell_env
from pico.tool_context import ToolContext
from pico.workspace import resolve_in_workspace


def make_ctx(root: Path) -> ToolContext:
    return ToolContext(
        root=root,
        path_resolver=lambda raw: resolve_in_workspace(root, raw),
        shell_env_provider=safe_shell_env,
    )


class LabFlowWriteGuardTests(unittest.TestCase):
    def test_generate_report_refuses_findings_path_inside_data(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "outputs" / "batch_001").mkdir(parents=True)
            fake_findings = root / "data" / "batch_001" / "qc_summary.csv"
            fake_findings.parent.mkdir(parents=True)
            fake_findings.write_text("finding_id\nF0001\n", encoding="utf-8")
            ctx = make_ctx(root)
            with self.assertRaises(SafetyViolationError):
                tool_generate_report(
                    ctx,
                    {"batch_id": "batch_001", "findings_path": str(fake_findings.relative_to(root))},
                )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_phase1_labflow_write_guard.py -v`
Expected: FAIL — `tool_generate_report` does not call the guard, so no `SafetyViolationError` is raised; `assertRaises` fails.

- [ ] **Step 3: Add the import and guard calls**

In `pico/labflow_tools.py`, extend the existing `from .safety.guard import (...)` block to also import `assert_raw_data_readonly`. The import becomes:

```python
from .safety.guard import (
    assert_raw_data_readonly,
    resolve_output_path,
    resolve_preprocessed_path,
    resolve_registered_script,
    resolve_report_path,
    resolve_trace_path,
    resolve_workspace_path,
    sanitize_batch_id,
)
```

In `tool_generate_report`, right after computing `report_path = resolve_report_path(ctx.root, batch_id)` (before `report_path.parent.mkdir(...)`), insert:

```python
    assert_raw_data_readonly(ctx.root, report_path)
    assert_raw_data_readonly(ctx.root, qc_path)
```

In `tool_export_workflow_log`, right after `trace_path = resolve_trace_path(ctx.root, batch_id)`, insert:

```python
    assert_raw_data_readonly(ctx.root, trace_path)
```

In `_run_single_preprocess` and `_run_batch_preprocess`, after `output_path = resolve_preprocessed_path(...)` is computed, insert `assert_raw_data_readonly(ctx.root, output_path)` before the subprocess call. In `_run_single_preprocess` insert after the `output_path = resolve_preprocessed_path(ctx.root, batch_id, output_name)` line:

```python
    assert_raw_data_readonly(ctx.root, output_path)
```

In `_run_batch_preprocess`, inside the `for input_path in candidates:` loop, after `output_path = resolve_preprocessed_path(ctx.root, batch_id, output_name)`, insert:

```python
        assert_raw_data_readonly(ctx.root, output_path)
```

In `tool_quality_check`, after `qc_path = resolve_output_path(ctx.root, batch_id, "qc_summary.csv")`, insert:

```python
    assert_raw_data_readonly(ctx.root, qc_path)
```

- [ ] **Step 4: Run the new test plus the full labflow suite**

Run: `python -m pytest tests/test_phase1_labflow_write_guard.py tests/test_labflow_tools.py tests/test_labflow_reports.py tests/test_safety_boundaries.py tests/test_batch_preprocess.py -v`
Expected: PASS. (Write targets under `outputs/`, `reports/`, `traces/` are outside `data/`, so the guard never fires for legitimate writes.)

- [ ] **Step 5: Lint and commit**

```bash
ruff check pico/labflow_tools.py tests/test_phase1_labflow_write_guard.py
git add pico/labflow_tools.py tests/test_phase1_labflow_write_guard.py
git commit -m "feat(labflow): enforce raw-data read-only on all write paths"
```

---

## Task 4: Three-tier exception handling in `ToolExecutor`

**Files:**
- Modify: `pico/tool_executor.py:45-50`

**Interfaces:**
- Consumes: `SafetyViolationError`, `ToolExecutionError` from Task 1.
- Produces: `ToolExecutor.execute` lets `SafetyViolationError` propagate, converts `ToolExecutionError` to `ToolResult(success=False, error_code=err.error_code)`, and logs unexpected `Exception` with a `warning` flag.

- [ ] **Step 1: Write the failing test**

Create `tests/test_phase1_executor_tiers.py`:

```python
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pico.errors import SafetyViolationError, ToolExecutionError
from pico.security import safe_shell_env
from pico.tool_context import ToolContext
from pico.tool_executor import ToolExecutor
from pico.tools import ToolResult, ToolSpec
from pico.workspace import resolve_in_workspace


def make_executor(root: Path, runner) -> ToolExecutor:
    ctx = ToolContext(
        root=root,
        path_resolver=lambda raw: resolve_in_workspace(root, raw),
        shell_env_provider=safe_shell_env,
    )
    registry = {"probe": ToolSpec("probe", "probe", {"type": "object", "properties": {}, "required": []}, False, runner)}
    return ToolExecutor(registry=registry, context=ctx, approval="auto")


class ExecutorTierTests(unittest.TestCase):
    def test_safety_violation_propagates(self):
        def runner(ctx, args):
            raise SafetyViolationError("nope")

        with TemporaryDirectory() as d:
            executor = make_executor(Path(d), runner)
            with self.assertRaises(SafetyViolationError):
                executor.execute("probe", {})

    def test_tool_execution_error_becomes_result(self):
        def runner(ctx, args):
            raise ToolExecutionError("missing file", error_code="not_found")

        with TemporaryDirectory() as d:
            executor = make_executor(Path(d), runner)
            result = executor.execute("probe", {})
            self.assertFalse(result.ok)
            self.assertEqual(result.error_code, "not_found")
            self.assertIn("missing file", result.text)

    def test_unexpected_exception_is_captured_and_warned(self):
        def runner(ctx, args):
            raise RuntimeError("boom")

        with TemporaryDirectory() as d:
            executor = make_executor(Path(d), runner)
            result = executor.execute("probe", {})
            self.assertFalse(result.ok)
            self.assertEqual(result.error_code, "tool_exception")
            self.assertTrue(any(evt.get("level") == "warning" for evt in executor.events))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_phase1_executor_tiers.py -v`
Expected: FAIL — current code catches `Exception` (which `SafetyViolationError` is), so the safety-violation test fails (`assertRaises` never sees it propagate); `events` does not exist yet.

- [ ] **Step 3: Rewrite the try/except block in `tool_executor.py`**

Add the import near the top of `pico/tool_executor.py` (after the existing `from .tools import ...` line):

```python
from .errors import SafetyViolationError, ToolExecutionError
```

Replace the try/except block (current lines 45-50):

```python
        try:
            return spec.runner(self.context, args)
        except ValueError as exc:
            return ToolResult(False, str(exc), error_code="path_escape")
        except Exception as exc:  # noqa: BLE001 - tool boundary must convert failures to observations
            return ToolResult(False, f"tool failed: {exc}", error_code="tool_exception")
```

with:

```python
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
```

- [ ] **Step 4: Run the new test plus the existing executor/safety tests**

Run: `python -m pytest tests/test_phase1_executor_tiers.py tests/test_tools_safety.py tests/test_safety_boundaries.py tests/test_tool_registry.py -v`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
ruff check pico/tool_executor.py tests/test_phase1_executor_tiers.py
git add pico/tool_executor.py tests/test_phase1_executor_tiers.py
git commit -m "feat(executor): three-tier exception handling, propagate SafetyViolationError"
```

---

## Task 5: Convert LabFlow business errors to `ToolExecutionError` and document generic tools

**Files:**
- Modify: `pico/labflow_tools.py` (selected error returns)
- Modify: `pico/tools.py` (module docstring only)

**Interfaces:**
- Consumes: `ToolExecutionError` from Task 1.
- Produces: known LabFlow failures raise `ToolExecutionError(error_code=...)`; the executor maps them to `ToolResult`. `tools.py` gains a docstring explaining the generic-vs-LabFlow registry split.

- [ ] **Step 1: Write the failing test**

Create `tests/test_phase1_labflow_error_codes.py`:

```python
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pico.errors import ToolExecutionError
from pico.labflow_tools import tool_inspect_table, tool_summarize_outputs
from pico.security import safe_shell_env
from pico.tool_context import ToolContext
from pico.workspace import resolve_in_workspace


def make_ctx(root: Path) -> ToolContext:
    return ToolContext(
        root=root,
        path_resolver=lambda raw: resolve_in_workspace(root, raw),
        shell_env_provider=safe_shell_env,
    )


class LabFlowErrorCodeTests(unittest.TestCase):
    def test_inspect_missing_file_raises_not_found(self):
        with TemporaryDirectory() as d:
            ctx = make_ctx(Path(d))
            with self.assertRaises(ToolExecutionError) as cm:
                tool_inspect_table(ctx, {"path": "missing.csv"})
            self.assertEqual(cm.exception.error_code, "not_file")

    def test_summarize_missing_batch_raises_not_found(self):
        with TemporaryDirectory() as d:
            ctx = make_ctx(Path(d))
            with self.assertRaises(ToolExecutionError) as cm:
                tool_summarize_outputs(ctx, {"batch_id": "ghost"})
            self.assertEqual(cm.exception.error_code, "not_found")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_phase1_labflow_error_codes.py -v`
Expected: FAIL — these functions currently `return ToolResult(False, ..., error_code=...)` rather than raising.

- [ ] **Step 3: Add import and convert the two targeted errors**

In `pico/labflow_tools.py`, add to the imports (near the top, after the `from .safety.guard import (...)` block):

```python
from .errors import ToolExecutionError
```

In `tool_inspect_table`, replace:

```python
    if not path.is_file():
        return ToolResult(False, f"not a file: {relpath(ctx, path)}", error_code="not_file")
```

with:

```python
    if not path.is_file():
        raise ToolExecutionError(f"not a file: {relpath(ctx, path)}", error_code="not_file")
```

In `tool_summarize_outputs`, replace:

```python
    if not output_dir.exists():
        return ToolResult(False, f"output directory not found: outputs/{batch_id}", error_code="not_found")
```

with:

```python
    if not output_dir.exists():
        raise ToolExecutionError(f"output directory not found: outputs/{batch_id}", error_code="not_found")
```

Leave all other error returns as-is for this task — they still work via the executor's `Exception` fallback; they will be migrated incrementally in later phases as needed.

- [ ] **Step 4: Add a clarifying module docstring to `tools.py`**

At the very top of `pico/tools.py` (before `from __future__ import annotations` is fine, as a string is not allowed there — place it as the first statement after the imports instead). Insert this docstring as the module's first statement (before `@dataclass class ToolResult`):

```python
"""Generic pico-harness tools and tool primitives.

This module defines the generic agent tool registry (list_files, read_file,
search, run_shell, write_file, patch_file, delegate) plus the shared
ToolSpec/ToolResult primitives. The generic registry is the safety test bed
exercised by tests/test_tools_safety.py and is intentionally separate from the
LabFlow registry in pico/tool_registry.py, which is what the LabFlow runtime
actually exposes (safety-by-default: no arbitrary shell/file-write tools).
"""
```

- [ ] **Step 5: Run the new test plus the full labflow and tool-registry suites**

Run: `python -m pytest tests/test_phase1_labflow_error_codes.py tests/test_labflow_tools.py tests/test_labflow_reports.py tests/test_safety_boundaries.py tests/test_tool_registry.py -v`
Expected: PASS. (Existing tests that called these tools directly and checked `result.ok is False` may need updating — if a test calls `tool_inspect_table` directly and expects a `ToolResult`, update it to expect `ToolExecutionError`. Run Task 7's sweep to catch these.)

- [ ] **Step 6: Lint and commit**

```bash
ruff check pico/labflow_tools.py pico/tools.py tests/test_phase1_labflow_error_codes.py
git add pico/labflow_tools.py pico/tools.py tests/test_phase1_labflow_error_codes.py
git commit -m "feat(labflow): raise ToolExecutionError for known business errors; document generic registry"
```

---

## Task 6: Delete the unused shim modules

**Files:**
- Delete: `pico/agent_loop.py`
- Delete: `pico/session_store.py`

**Interfaces:**
- Consumes: verified zero references (all `SessionStore` imports come from `pico.run_store`; all `Pico` imports come from `pico.runtime`).

- [ ] **Step 1: Confirm zero references one more time**

Run: `grep -rn "agent_loop\|from pico.session_store\|from \.session_store" pico/ tests/`
Expected: no output (no matches). If any match appears, stop and fix that import first.

- [ ] **Step 2: Delete the two files**

```bash
git rm pico/agent_loop.py pico/session_store.py
```

- [ ] **Step 3: Run the full test suite**

Run: `python -m pytest tests/ -q`
Expected: PASS (all tests green; nothing imported the shims).

- [ ] **Step 4: Lint and commit**

```bash
ruff check pico/
git commit -m "chore: remove unused agent_loop.py and session_store.py re-export shims"
```

---

## Task 7: Sweep and fix any tests broken by typed exceptions

**Files:**
- Modify: as needed — `tests/test_labflow_guard.py`, `tests/test_labflow_tools.py`, `tests/test_safety_boundaries.py`, or any test that called a converted tool directly and asserted on a returned `ToolResult`.

- [ ] **Step 1: Run the whole suite and capture failures**

Run: `python -m pytest tests/ -q`
Expected: any test that called `tool_inspect_table` / `tool_summarize_outputs` directly and asserted `.ok is False` / `.error_code` now fails because the function raises.

- [ ] **Step 2: Fix each broken test**

For each failure, wrap the direct tool call in `assertRaises(ToolExecutionError)` and assert `cm.exception.error_code`. Example transformation:

Before:
```python
result = tool_inspect_table(ctx, {"path": "missing.csv"})
self.assertFalse(result.ok)
self.assertEqual(result.error_code, "not_file")
```

After:
```python
from pico.errors import ToolExecutionError
with self.assertRaises(ToolExecutionError) as cm:
    tool_inspect_table(ctx, {"path": "missing.csv"})
self.assertEqual(cm.exception.error_code, "not_file")
```

For tests that exercise the same tools *through the executor* (`ToolExecutor.execute`), no change is needed — the executor converts the exception back into a `ToolResult`.

- [ ] **Step 3: Re-run the whole suite**

Run: `python -m pytest tests/ -q`
Expected: PASS — all green.

- [ ] **Step 4: Lint and commit**

```bash
ruff check tests/
git add tests/
git commit -m "test: adapt direct tool-call tests to ToolExecutionError"
```

---

## Phase 1 Acceptance

- [ ] `python -m pytest tests/ -q` is fully green.
- [ ] `ruff check .` reports no issues.
- [ ] `grep -rn "agent_loop\|from pico.session_store\|from \.session_store" pico/ tests/` returns nothing.
- [ ] A new test demonstrates that writing under `data/batch_*/` or `data/raw/` raises `SafetyViolationError`.
- [ ] `ToolExecutor.execute` lets `SafetyViolationError` propagate (verified by test).
