from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pico.security import safe_shell_env
from pico.tool_context import ToolContext
from pico.tool_executor import ToolExecutor
from pico.tool_registry import build_labflow_tool_registry, build_tool_registry
from pico.workspace import resolve_in_workspace

EXPECTED_TOOLS = {
    "scan_experiment_dir",
    "inspect_table",
    "quality_check",
    "run_preprocess_script",
    "summarize_outputs",
    "generate_report",
    "export_workflow_log",
}


def make_context(root: Path) -> ToolContext:
    return ToolContext(
        root=root,
        path_resolver=lambda raw: resolve_in_workspace(root, raw),
        shell_env_provider=safe_shell_env,
    )


class LabFlowToolRegistryTests(unittest.TestCase):
    def test_labflow_registry_exposes_expected_tools_only(self):
        with TemporaryDirectory() as directory:
            ctx = make_context(Path(directory))
            registry = build_tool_registry(ctx)
            self.assertEqual(set(registry), EXPECTED_TOOLS)
            self.assertEqual(set(build_labflow_tool_registry(ctx)), EXPECTED_TOOLS)
            self.assertNotIn("run_shell", registry)
            self.assertNotIn("write_file", registry)
            self.assertNotIn("patch_file", registry)

    def test_registered_tools_have_schema_and_risk_flags(self):
        with TemporaryDirectory() as directory:
            registry = build_tool_registry(make_context(Path(directory)))
            for name, spec in registry.items():
                self.assertEqual(spec.name, name)
                self.assertIn("properties", spec.schema)
                self.assertIn("required", spec.schema)
                self.assertIsInstance(spec.risky, bool)
            self.assertTrue(registry["run_preprocess_script"].risky)
            self.assertFalse(registry["quality_check"].risky)

    def test_unknown_coding_tool_is_not_available_in_labflow_mode(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            executor = ToolExecutor(
                build_tool_registry(make_context(root)), make_context(root), approval="auto"
            )
            result = executor.execute("run_shell", {"command": "python --version"})
            self.assertFalse(result.ok)
            self.assertEqual(result.error_code, "unknown_tool")


if __name__ == "__main__":
    unittest.main()
