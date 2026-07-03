from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pico.labflow_tools import tool_generate_report, tool_quality_check, tool_summarize_outputs
from pico.safety.guard import resolve_output_path, resolve_report_path, resolve_trace_path
from pico.security import safe_shell_env
from pico.tool_context import ToolContext
from pico.tool_executor import ToolExecutor
from pico.tool_registry import build_tool_registry
from pico.workspace import resolve_in_workspace


def make_context(root: Path) -> ToolContext:
    return ToolContext(
        root=root,
        path_resolver=lambda raw: resolve_in_workspace(root, raw),
        shell_env_provider=safe_shell_env,
    )


class SafetyBoundariesTests(unittest.TestCase):
    def test_invalid_batch_id_is_rejected_by_writing_tools(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            batch = root / "data" / "batch_demo_001"
            (batch / "spectra").mkdir(parents=True)
            (batch / "metadata.csv").write_text("sample_id,method\ns1,raman\n", encoding="utf-8")
            ctx = make_context(root)
            with self.assertRaises(ValueError):
                tool_quality_check(ctx, {"experiment_dir": "data/batch_demo_001", "batch_id": "../bad"})
            with self.assertRaises(ValueError):
                tool_summarize_outputs(ctx, {"batch_id": "../bad"})
            with self.assertRaises(ValueError):
                tool_generate_report(ctx, {"batch_id": "../bad"})

    def test_output_report_and_trace_paths_are_constrained(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                resolve_output_path(root, "batch_demo_001", "../escape.csv")
            self.assertEqual(resolve_report_path(root, "batch_demo_001"), root.resolve() / "reports" / "batch_demo_001_qc_report.md")
            self.assertEqual(resolve_trace_path(root, "batch_demo_001"), root.resolve() / "traces" / "batch_demo_001_workflow_log.json")

    def test_labflow_registry_does_not_expose_coding_write_tools(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            executor = ToolExecutor(build_tool_registry(make_context(root)), make_context(root), approval="auto")
            for name, args in [
                ("run_shell", {"command": "python --version"}),
                ("write_file", {"path": "x.txt", "content": "x"}),
                ("patch_file", {"path": "x.txt", "old_text": "x", "new_text": "y"}),
            ]:
                result = executor.execute(name, args)
                self.assertFalse(result.ok)
                self.assertEqual(result.error_code, "unknown_tool")


if __name__ == "__main__":
    unittest.main()
