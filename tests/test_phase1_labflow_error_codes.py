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
