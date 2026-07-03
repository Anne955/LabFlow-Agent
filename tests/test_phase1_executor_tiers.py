from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pico.errors import SafetyViolationError, ToolExecutionError
from pico.security import safe_shell_env
from pico.tool_context import ToolContext
from pico.tool_executor import ToolExecutor
from pico.tools import ToolSpec
from pico.workspace import resolve_in_workspace


def make_executor(root: Path, runner) -> ToolExecutor:
    ctx = ToolContext(
        root=root,
        path_resolver=lambda raw: resolve_in_workspace(root, raw),
        shell_env_provider=safe_shell_env,
    )
    schema = {"type": "object", "properties": {}, "required": []}
    registry = {"probe": ToolSpec("probe", "probe", schema, False, runner)}
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
